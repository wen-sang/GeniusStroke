from __future__ import annotations

from collections import defaultdict

from core.data_quality.models import EntityType
from core.data_quality.models import IssueGroup
from core.data_quality.models import IssueSeverity
from core.data_quality.rules.common import affected_detail
from core.data_quality.rules.common import is_valid_date
from core.data_quality.rules.common import issue
from core.data_quality.rules.common import market_entity_id
from core.data_quality.rules.common import resolve_source_id
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
        if (
            calendar_min is None
            or calendar_max is None
            or market_min < calendar_min
            or market_max > calendar_max
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
