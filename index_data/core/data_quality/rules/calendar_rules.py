from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from datetime import timedelta

from core.data_quality.models import EntityType
from core.data_quality.models import IssueGroup
from core.data_quality.models import IssueSeverity
from core.data_quality.rules.common import affected_detail
from core.data_quality.rules.common import is_valid_date
from core.data_quality.rules.common import issue
from core.data_quality.rules.common import market_entity_id
from core.data_quality.rules.common import resolve_source_id
from core.data_quality.rules.common import source_distribution
from core.data_quality.rules.common import valid_exchange


def scan(
    rows: list[dict],
    calendar_rows: list[dict],
    scan_batch_id: str,
    detected_at: str,
) -> list:
    issues = []
    calendar_by_key = {
        (row.get("exchange"), row.get("calendar_date")): row
        for row in calendar_rows
    }
    issues.extend(
        _scan_coverage(rows, calendar_rows, scan_batch_id, detected_at)
    )
    issues.extend(
        _scan_invalid_is_open(rows, calendar_rows, scan_batch_id, detected_at)
    )
    issues.extend(
        _scan_missing_trading_day_bar(
            rows,
            calendar_by_key,
            scan_batch_id,
            detected_at,
        )
    )

    for row in rows:
        exchange = row.get("exchange")
        trade_date = row.get("trade_date")
        if not valid_exchange(exchange) or not is_valid_date(trade_date):
            continue
        calendar_row = calendar_by_key.get((exchange, trade_date))
        if calendar_row is None:
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.MARKET_ROW,
                    market_entity_id(row),
                    "CALENDAR_RECORD_MISSING",
                    IssueSeverity.ERROR,
                    IssueGroup.CALENDAR,
                    "calendar_date",
                    None,
                    "calendar record exists",
                    {"exchange": exchange},
                    asset_code=row.get("asset_code"),
                    trade_date=trade_date,
                    source_id=row.get("source_id"),
                )
            )
            continue
        if calendar_row.get("is_open") == 0:
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.MARKET_ROW,
                    market_entity_id(row),
                    "NON_TRADING_DAY_BAR",
                    IssueSeverity.WARN,
                    IssueGroup.CALENDAR,
                    "trade_date",
                    "bar exists",
                    "no bar on closed date",
                    {"exchange": exchange, "is_open": 0},
                    asset_code=row.get("asset_code"),
                    trade_date=trade_date,
                    source_id=row.get("source_id"),
                )
            )

    return issues


def _scan_coverage(
    rows: list[dict],
    calendar_rows: list[dict],
    scan_batch_id: str,
    detected_at: str,
) -> list:
    issues = []
    market_by_exchange = defaultdict(list)
    for row in rows:
        if valid_exchange(row.get("exchange")) and is_valid_date(row.get("trade_date")):
            market_by_exchange[row["exchange"]].append(row)

    calendar_by_exchange = defaultdict(list)
    for row in calendar_rows:
        if valid_exchange(row.get("exchange")) and is_valid_date(
            row.get("calendar_date")
        ):
            calendar_by_exchange[row["exchange"]].append(row)

    for exchange, exchange_rows in market_by_exchange.items():
        market_dates = [row["trade_date"] for row in exchange_rows]
        calendar_dates = [
            row["calendar_date"]
            for row in calendar_by_exchange.get(exchange, [])
        ]
        market_min = min(market_dates)
        market_max = max(market_dates)
        calendar_min = min(calendar_dates) if calendar_dates else None
        calendar_max = max(calendar_dates) if calendar_dates else None
        range_covered = (
            calendar_min is not None
            and calendar_max is not None
            and market_min >= calendar_min
            and market_max <= calendar_max
        )
        missing_calendar_dates = []
        if range_covered:
            missing_calendar_dates = _missing_natural_dates(
                calendar_dates,
                market_min,
                market_max,
            )
        if (
            calendar_min is None
            or calendar_max is None
            or market_min < calendar_min
            or market_max > calendar_max
            or missing_calendar_dates
        ):
            detail = {
                "exchange": exchange,
                "market_min_trade_date": market_min,
                "market_max_trade_date": market_max,
                "calendar_min_date": calendar_min,
                "calendar_max_date": calendar_max,
                "source_distribution": affected_detail(
                    exchange_rows
                )["source_distribution"],
            }
            if missing_calendar_dates:
                detail.update(
                    {
                        "coverage_violation": "internal_calendar_gap",
                        "missing_date_count": len(missing_calendar_dates),
                        "missing_calendar_dates": missing_calendar_dates,
                        "missing_calendar_dates_truncated": False,
                    }
                )
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.EXCHANGE,
                    exchange,
                    "CALENDAR_COVERAGE_INSUFFICIENT",
                    IssueSeverity.ERROR,
                    IssueGroup.CALENDAR,
                    "calendar_date",
                    f"{market_min}..{market_max}",
                    f"{calendar_min}..{calendar_max}",
                    detail,
                    source_id=resolve_source_id(exchange_rows),
                )
            )
    return issues


def _scan_missing_trading_day_bar(
    rows: list[dict],
    calendar_by_key: dict[tuple, dict],
    scan_batch_id: str,
    detected_at: str,
) -> list:
    rows_by_asset = defaultdict(list)
    for row in rows:
        asset_code = row.get("asset_code")
        if not asset_code:
            continue
        rows_by_asset[asset_code].append(row)

    issues = []
    for asset_code, asset_rows in rows_by_asset.items():
        first_row = asset_rows[0]
        exchange = first_row.get("exchange")
        listing_date = first_row.get("listing_date")
        if not valid_exchange(exchange):
            continue

        trade_dates = {
            row.get("trade_date")
            for row in asset_rows
            if is_valid_date(row.get("trade_date"))
        }
        if not trade_dates:
            continue

        asset_min_trade_date = min(trade_dates)
        asset_max_trade_date = max(trade_dates)
        effective_start_date = asset_min_trade_date
        if effective_start_date > asset_max_trade_date:
            continue

        for calendar_date in _date_range(
            effective_start_date,
            asset_max_trade_date,
        ):
            calendar_row = calendar_by_key.get((exchange, calendar_date))
            if calendar_row is None or calendar_row.get("is_open") != 1:
                continue
            if calendar_date in trade_dates:
                continue
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.ASSET,
                    asset_code,
                    "MISSING_TRADING_DAY_BAR",
                    IssueSeverity.WARN,
                    IssueGroup.CALENDAR,
                    "trade_date",
                    "missing bar",
                    "market bar exists on open trading day",
                    {
                        "exchange": exchange,
                        "calendar_date": calendar_date,
                        "listing_date": listing_date,
                        "asset_min_trade_date": asset_min_trade_date,
                        "asset_max_trade_date": asset_max_trade_date,
                        "effective_start_date": effective_start_date,
                        "is_open": 1,
                        "source_distribution": source_distribution(asset_rows),
                        "missing_reason": (
                            "open_trading_day_without_market_row"
                        ),
                    },
                    asset_code=asset_code,
                    trade_date=calendar_date,
                    source_id=None,
                )
            )
    return issues


def _scan_invalid_is_open(
    rows: list[dict],
    calendar_rows: list[dict],
    scan_batch_id: str,
    detected_at: str,
) -> list:
    valid_trade_dates = [
        row.get("trade_date")
        for row in rows
        if is_valid_date(row.get("trade_date"))
    ]
    exchanges = {
        row.get("exchange")
        for row in rows
        if valid_exchange(row.get("exchange"))
    }
    if not valid_trade_dates or not exchanges:
        return []

    min_date = min(valid_trade_dates)
    max_date = max(valid_trade_dates)
    issues = []
    for row in calendar_rows:
        exchange = row.get("exchange")
        calendar_date = row.get("calendar_date")
        if exchange not in exchanges or not is_valid_date(calendar_date):
            continue
        if calendar_date < min_date or calendar_date > max_date:
            continue
        if row.get("is_open") in (0, 1):
            continue
        entity_id = f"{exchange}|{calendar_date}"
        issues.append(
            issue(
                scan_batch_id,
                detected_at,
                EntityType.CALENDAR_DATE,
                entity_id,
                "CALENDAR_INVALID_IS_OPEN",
                IssueSeverity.ERROR,
                IssueGroup.CALENDAR,
                "is_open",
                row.get("is_open"),
                "0 or 1",
                {
                    "exchange": exchange,
                    "calendar_date": calendar_date,
                    "is_open": row.get("is_open"),
                },
                trade_date=calendar_date,
                source_id=None,
            )
        )
    return issues


def _missing_natural_dates(
    calendar_dates: list[str],
    start_date: str,
    end_date: str,
) -> list[str]:
    calendar_set = set(calendar_dates)
    return [
        candidate
        for candidate in _date_range(start_date, end_date)
        if candidate not in calendar_set
    ]


def _date_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    result = []
    current = start
    while current <= end:
        result.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return result
