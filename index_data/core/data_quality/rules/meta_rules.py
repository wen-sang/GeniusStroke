from __future__ import annotations

from collections import defaultdict

from config.constants import Exchange
from core.data_quality.models import EntityType
from core.data_quality.models import IssueGroup
from core.data_quality.models import IssueSeverity
from core.data_quality.rules.common import affected_detail
from core.data_quality.rules.common import date_parse_error
from core.data_quality.rules.common import is_missing
from core.data_quality.rules.common import is_valid_date
from core.data_quality.rules.common import issue
from core.data_quality.rules.common import market_entity_id
from core.data_quality.rules.common import resolve_source_id


def scan(
    rows: list[dict],
    scan_batch_id: str,
    detected_at: str,
) -> list:
    issues = []
    by_asset = _group_rows_by_asset(rows)

    for asset_code, asset_rows in by_asset.items():
        first = asset_rows[0]
        if first.get("meta_asset_code") is None:
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.ASSET,
                    asset_code,
                    "ASSET_META_MISSING",
                    IssueSeverity.ERROR,
                    IssueGroup.META,
                    "asset_code",
                    asset_code,
                    "exists in sys_asset_meta",
                    affected_detail(asset_rows),
                    asset_code=asset_code,
                    source_id=resolve_source_id(asset_rows),
                )
            )
            continue

        exchange = first.get("exchange")
        if is_missing(exchange):
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.ASSET,
                    asset_code,
                    "ASSET_EXCHANGE_MISSING",
                    IssueSeverity.ERROR,
                    IssueGroup.META,
                    "exchange",
                    "",
                    "SH/SZ/HK",
                    affected_detail(asset_rows),
                    asset_code=asset_code,
                    source_id=resolve_source_id(asset_rows),
                )
            )
        elif str(exchange).strip() not in Exchange.VALID:
            detail = {
                "exchange": exchange,
                **affected_detail(asset_rows),
            }
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.ASSET,
                    asset_code,
                    "ASSET_EXCHANGE_INVALID",
                    IssueSeverity.ERROR,
                    IssueGroup.META,
                    "exchange",
                    exchange,
                    "SH/SZ/HK",
                    detail,
                    asset_code=asset_code,
                    source_id=resolve_source_id(asset_rows),
                )
            )

        listing_date = first.get("listing_date")
        listing_error = _listing_date_error(listing_date)
        if listing_error:
            detail = {
                "listing_date": listing_date or "",
                "invalid_reason": listing_error,
                **affected_detail(asset_rows),
            }
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.ASSET,
                    asset_code,
                    "LISTING_DATE_INVALID",
                    IssueSeverity.WARN,
                    IssueGroup.META,
                    "listing_date",
                    listing_date,
                    "YYYY-MM-DD",
                    detail,
                    asset_code=asset_code,
                    source_id=resolve_source_id(asset_rows),
                )
            )

    for row in rows:
        listing_date = row.get("listing_date")
        trade_date = row.get("trade_date")
        if not is_valid_date(trade_date) or not is_valid_date(listing_date):
            continue
        if trade_date < listing_date:
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.MARKET_ROW,
                    market_entity_id(row),
                    "BAR_BEFORE_LISTING_DATE",
                    IssueSeverity.WARN,
                    IssueGroup.META,
                    "trade_date",
                    trade_date,
                    ">= listing_date",
                    {"listing_date": listing_date},
                    asset_code=row.get("asset_code"),
                    trade_date=trade_date,
                    source_id=row.get("source_id"),
                )
            )

    return issues


def _group_rows_by_asset(rows: list[dict]) -> dict[str, list[dict]]:
    by_asset = defaultdict(list)
    for row in rows:
        asset_code = row.get("asset_code")
        if is_missing(asset_code):
            continue
        by_asset[str(asset_code)].append(row)
    return dict(by_asset)


def _listing_date_error(value) -> str | None:
    if is_missing(value):
        return "empty"
    parse_error = date_parse_error(value)
    if parse_error:
        return parse_error
    return None
