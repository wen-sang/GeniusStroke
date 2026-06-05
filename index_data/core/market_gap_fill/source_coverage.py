from __future__ import annotations

from collections import Counter
from collections import defaultdict
from datetime import datetime

from config.constants import AssetType
from config.constants import Exchange
from core.market_gap_fill.models import MarketGapFillRunOptions
from core.market_gap_fill.tdx_day_parser import get_bar_for_date
from core.market_gap_fill.tdx_vipdoc_refresh import current_package_covers
from core.market_gap_fill.tdx_vipdoc_refresh import current_package_dir
from dao.data_quality_dao import data_quality_dao
from dao.market_gap_fill_dao import market_gap_fill_dao


ELIGIBLE_ASSET_TYPES = {AssetType.STOCK, AssetType.ETF, AssetType.LOF}


def check_gap_source_coverage(
    target_date: str,
    options: MarketGapFillRunOptions | None = None,
) -> dict:
    options = options or MarketGapFillRunOptions()
    market_rows = data_quality_dao.fetch_market_daily_rows()
    calendar_rows = data_quality_dao.fetch_exchange_calendar_rows()
    open_dates_by_exchange = _open_dates_by_exchange(calendar_rows, target_date)
    dates_by_asset, meta_by_asset = _market_state(market_rows)

    gap_count = 0
    samples = []
    tdx_status_counts = Counter()
    tickflow_catalog_counts = Counter()
    combined_counts = Counter()
    sample_limit = options.normalized_limit(100)
    tdx_covers_target = current_package_covers(target_date)

    for asset_code in sorted(dates_by_asset):
        meta = meta_by_asset.get(asset_code) or {}
        exchange = meta.get("exchange")
        asset_type = meta.get("asset_type")
        if not _is_eligible(asset_code, exchange, asset_type, options):
            continue

        known_dates = dates_by_asset[asset_code]
        if not known_dates:
            continue
        min_date = min(known_dates)
        max_date = min(max(known_dates), target_date)
        for trade_date in open_dates_by_exchange.get(exchange, []):
            if trade_date < min_date or trade_date > max_date:
                continue
            if trade_date in known_dates or not _matches_date(trade_date, options):
                continue

            gap_count += 1
            tdx_status = _resolve_tdx_status(
                target_date=target_date,
                tdx_covers_target=tdx_covers_target,
                exchange=exchange,
                asset_code=asset_code,
                asset_type=asset_type,
                trade_date=trade_date,
            )
            tickflow_status = _resolve_tickflow_catalog_status(asset_code, asset_type)
            tdx_status_counts[tdx_status] += 1
            tickflow_catalog_counts[tickflow_status] += 1
            combined_counts[f"tdx={tdx_status}|tickflow_catalog={tickflow_status}"] += 1

            if len(samples) < sample_limit:
                samples.append(
                    {
                        "asset_code": asset_code,
                        "exchange": exchange,
                        "asset_type": asset_type,
                        "missing_date": trade_date,
                        "tdx_status": tdx_status,
                        "tickflow_catalog_status": tickflow_status,
                    }
                )

    return {
        "target_date": target_date,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "gap_count": gap_count,
        "tdx_status_counts": dict(sorted(tdx_status_counts.items())),
        "tickflow_catalog_counts": dict(sorted(tickflow_catalog_counts.items())),
        "combined_counts": dict(sorted(combined_counts.items())),
        "sample_count": len(samples),
        "samples": samples,
    }


def _resolve_tdx_status(
    target_date: str,
    tdx_covers_target: bool,
    exchange: str,
    asset_code: str,
    asset_type: str,
    trade_date: str,
) -> str:
    if not (
        exchange in {Exchange.SH, Exchange.SZ}
        and asset_type in ELIGIBLE_ASSET_TYPES
    ):
        return "skipped_not_applicable"
    if not tdx_covers_target:
        return "skipped_stale_or_missing"
    try:
        bar = get_bar_for_date(
            root=current_package_dir(),
            exchange=exchange,
            asset_code=asset_code,
            asset_type=asset_type,
            trade_date=trade_date,
        )
    except Exception as exc:
        return f"failed:{exc.__class__.__name__}"
    if not bar:
        return "empty"
    if bar.volume == 0 and bar.amount == 0:
        return "skipped_zero_volume_amount"
    return "hit"


def _resolve_tickflow_catalog_status(asset_code: str, asset_type: str) -> str:
    if asset_type == AssetType.LOF:
        return "unsupported_lof"
    return market_gap_fill_dao.get_tickflow_catalog_status(asset_code)


def _open_dates_by_exchange(
    calendar_rows: list[dict],
    target_date: str,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in calendar_rows:
        if row.get("is_open") != 1:
            continue
        exchange = row.get("exchange")
        date = row.get("calendar_date")
        if exchange and date and date <= target_date:
            result[exchange].append(date)
    for dates in result.values():
        dates.sort()
    return result


def _market_state(
    market_rows: list[dict],
) -> tuple[dict[str, set[str]], dict[str, dict]]:
    dates_by_asset: dict[str, set[str]] = defaultdict(set)
    meta_by_asset = {}
    for row in market_rows:
        asset_code = row.get("asset_code")
        trade_date = row.get("trade_date")
        if not asset_code or not trade_date:
            continue
        dates_by_asset[asset_code].add(trade_date)
        meta_by_asset[asset_code] = {
            "exchange": row.get("exchange"),
            "asset_type": row.get("asset_type"),
        }
    return dates_by_asset, meta_by_asset


def _is_eligible(
    asset_code: str,
    exchange: str | None,
    asset_type: str | None,
    options: MarketGapFillRunOptions,
) -> bool:
    if options.asset_code and asset_code != options.asset_code:
        return False
    return exchange in {Exchange.SH, Exchange.SZ} and asset_type in ELIGIBLE_ASSET_TYPES


def _matches_date(
    trade_date: str,
    options: MarketGapFillRunOptions,
) -> bool:
    if options.start_date and trade_date < options.start_date:
        return False
    if options.end_date and trade_date > options.end_date:
        return False
    return True
