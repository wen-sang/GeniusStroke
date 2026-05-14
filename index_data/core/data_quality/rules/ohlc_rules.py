from __future__ import annotations

from decimal import Decimal
from decimal import InvalidOperation
from decimal import ROUND_HALF_UP

from core.data_quality.models import EntityType
from core.data_quality.models import IssueGroup
from core.data_quality.models import IssueSeverity
from core.data_quality.rules.common import date_parse_error
from core.data_quality.rules.common import is_missing
from core.data_quality.rules.common import issue
from core.data_quality.rules.common import market_entity_id


PRICE_FIELDS = ("open", "high", "low", "close")


def scan(
    rows: list[dict],
    scan_batch_id: str,
    detected_at: str,
) -> list:
    issues = []
    for row in rows:
        issues.extend(_key_field_missing(row, scan_batch_id, detected_at))
        issues.extend(_date_format_invalid(row, scan_batch_id, detected_at))
        issues.extend(_price_non_positive(row, scan_batch_id, detected_at))
        issues.extend(_high_low_invalid(row, scan_batch_id, detected_at))
        issues.extend(_ohlc_range_invalid(row, scan_batch_id, detected_at))
        issues.extend(_only_close_available(row, scan_batch_id, detected_at))
    return issues


def _key_field_missing(row: dict, scan_batch_id: str, detected_at: str) -> list:
    issues = []
    for field in ("asset_code", "trade_date", "close"):
        if not is_missing(row.get(field)):
            continue
        issues.append(
            issue(
                scan_batch_id,
                detected_at,
                EntityType.MARKET_ROW,
                market_entity_id(row),
                "KEY_FIELD_MISSING",
                IssueSeverity.ERROR,
                IssueGroup.OHLC,
                field,
                row.get(field),
                "not null",
                {
                    "missing_field": field,
                    "market_row_id": row.get("market_row_id"),
                },
                asset_code=row.get("asset_code"),
                trade_date=row.get("trade_date"),
                source_id=row.get("source_id"),
            )
        )
    return issues


def _date_format_invalid(
    row: dict,
    scan_batch_id: str,
    detected_at: str,
) -> list:
    trade_date = row.get("trade_date")
    parse_error = date_parse_error(trade_date)
    if not parse_error:
        return []
    return [
        issue(
            scan_batch_id,
            detected_at,
            EntityType.MARKET_ROW,
            market_entity_id(row),
            "DATE_FORMAT_INVALID",
            IssueSeverity.ERROR,
            IssueGroup.OHLC,
            "trade_date",
            trade_date,
            "YYYY-MM-DD",
            {"trade_date": trade_date, "parse_error": parse_error},
            asset_code=row.get("asset_code"),
            trade_date=trade_date,
            source_id=row.get("source_id"),
        )
    ]


def _price_non_positive(
    row: dict,
    scan_batch_id: str,
    detected_at: str,
) -> list:
    issues = []
    for field in PRICE_FIELDS:
        value = _number(row.get(field))
        if value is None or value > 0:
            continue
        issues.append(
            issue(
                scan_batch_id,
                detected_at,
                EntityType.MARKET_ROW,
                market_entity_id(row),
                "PRICE_NON_POSITIVE",
                IssueSeverity.ERROR,
                IssueGroup.OHLC,
                field,
                row.get(field),
                "> 0",
                {
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "invalid_field": field,
                },
                asset_code=row.get("asset_code"),
                trade_date=row.get("trade_date"),
                source_id=row.get("source_id"),
            )
        )
    return issues


def _high_low_invalid(
    row: dict,
    scan_batch_id: str,
    detected_at: str,
) -> list:
    high = _number(row.get("high"))
    low = _number(row.get("low"))
    if high is None or low is None or low <= high:
        return []
    return [
        issue(
            scan_batch_id,
            detected_at,
            EntityType.MARKET_ROW,
            market_entity_id(row),
            "HIGH_LOW_INVALID",
            IssueSeverity.ERROR,
            IssueGroup.OHLC,
            "low_high",
            f"low={row.get('low')}, high={row.get('high')}",
            "low <= high",
            {"low": row.get("low"), "high": row.get("high")},
            asset_code=row.get("asset_code"),
            trade_date=row.get("trade_date"),
            source_id=row.get("source_id"),
        )
    ]


def _ohlc_range_invalid(
    row: dict,
    scan_batch_id: str,
    detected_at: str,
) -> list:
    high = _number(row.get("high"))
    low = _number(row.get("low"))
    if high is None or low is None or low > high:
        return []

    issues = []
    for field in ("open", "close"):
        value = _number(row.get(field))
        if value is None or low <= value <= high:
            continue
        rounded_bounds = None
        if field == "close":
            rounded_bounds = _rounded_price_bounds(row.get("close"), low, high)
            if rounded_bounds is not None:
                rounded_low, rounded_high = rounded_bounds
                if rounded_low <= value <= rounded_high:
                    continue
        violation = f"{field} < low" if value < low else f"{field} > high"
        detail = {
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "violation": violation,
        }
        if rounded_bounds is not None:
            rounded_low, rounded_high = rounded_bounds
            detail.update(
                {
                    "rounded_low": rounded_low,
                    "rounded_high": rounded_high,
                    "rounding_scale": _decimal_places(row.get("close")),
                }
            )
        issues.append(
            issue(
                scan_batch_id,
                detected_at,
                EntityType.MARKET_ROW,
                market_entity_id(row),
                "OHLC_RANGE_INVALID",
                IssueSeverity.ERROR,
                IssueGroup.OHLC,
                field,
                row.get(field),
                "[low, high]",
                detail,
                asset_code=row.get("asset_code"),
                trade_date=row.get("trade_date"),
                source_id=row.get("source_id"),
            )
        )
    return issues


def _rounded_price_bounds(value, low: float, high: float) -> tuple[float, float] | None:
    scale = _decimal_places(value)
    if scale is None:
        return None
    return (
        _round_half_up(low, scale),
        _round_half_up(high, scale),
    )


def _decimal_places(value) -> int | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    exponent = decimal_value.normalize().as_tuple().exponent
    return max(-exponent, 0)


def _round_half_up(value: float, places: int) -> float:
    quant = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def _only_close_available(
    row: dict,
    scan_batch_id: str,
    detected_at: str,
) -> list:
    if is_missing(row.get("close")):
        return []
    missing_fields = ["open", "high", "low", "volume", "amount"]
    if not all(is_missing(row.get(field)) for field in missing_fields):
        return []
    return [
        issue(
            scan_batch_id,
            detected_at,
            EntityType.MARKET_ROW,
            market_entity_id(row),
            "ONLY_CLOSE_AVAILABLE",
            IssueSeverity.WARN,
            IssueGroup.OHLC,
            "ohlcv",
            "close only",
            "open/high/low/volume/amount available",
            {"missing_fields": missing_fields},
            asset_code=row.get("asset_code"),
            trade_date=row.get("trade_date"),
            source_id=row.get("source_id"),
        )
    ]


def _number(value):
    if is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
