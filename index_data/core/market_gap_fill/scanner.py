from __future__ import annotations

from datetime import datetime, timedelta

from config.constants import AssetType, Exchange
from config.settings import (
    DATA_COLLECTION_DEFAULT_START_DATE,
    MARKET_GAP_FILL_MAX_NEW_TASKS_PER_RUN,
    MARKET_GAP_FILL_ZERO_HISTORY_DAYS_PER_ASSET,
)
from core.market_gap_fill.models import MarketGapFillRunOptions
from core.data_quality.models import EntityType, IssueGroup, IssueSeverity
from core.data_quality.rules import calendar_rules
from core.data_quality.rules.common import issue
from core.router import router
from dao.data_quality_dao import data_quality_dao
from dao.market_gap_fill_dao import market_gap_fill_dao
from dao.meta_dao import meta_dao
from utils.logger import logger


ELIGIBLE_ASSET_TYPES = {AssetType.STOCK, AssetType.ETF, AssetType.LOF}


class MarketGapScanner:
    """日常缺口轻量扫描，不生成 Excel 报告。"""

    def run(
        self,
        target_date: str,
        options: MarketGapFillRunOptions | None = None,
    ) -> dict:
        options = options or MarketGapFillRunOptions()
        scan_batch_id = "dq_gap_daily_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        started_at = _now_text()
        data_quality_dao.create_daily_gap_batch(scan_batch_id, started_at)
        scanned_rows = 0
        try:
            market_rows = data_quality_dao.fetch_market_daily_rows()
            calendar_rows = data_quality_dao.fetch_exchange_calendar_rows()
            scanned_rows = len(market_rows)
            detected_at = _now_text()
            issues = self._detect_internal_gaps(
                market_rows,
                calendar_rows,
                scan_batch_id,
                detected_at,
                options,
            )
            remaining_budget = max(
                0,
                MARKET_GAP_FILL_MAX_NEW_TASKS_PER_RUN - len(issues),
            )
            if remaining_budget > 0:
                issues.extend(
                    self._detect_zero_and_front_history_gaps(
                        market_rows=market_rows,
                        calendar_rows=calendar_rows,
                        target_date=target_date,
                        scan_batch_id=scan_batch_id,
                        detected_at=detected_at,
                        budget=remaining_budget,
                        options=options,
                    )
                )
            issue_count = data_quality_dao.complete_success_batch_without_report(
                scan_batch_id=scan_batch_id,
                issues=issues,
                scanned_rows=scanned_rows,
                finished_at=_now_text(),
            )
            task_issues = market_gap_fill_dao.list_missing_bar_issues_for_batch(
                scan_batch_id
            )
            generated_count = market_gap_fill_dao.upsert_tasks_from_issues(
                task_issues
            )
            logger.info(
                "[MARKET_GAP_SCAN] batch=%s issues=%s tasks=%s",
                scan_batch_id,
                issue_count,
                generated_count,
            )
            return {
                "scan_batch_id": scan_batch_id,
                "issue_count": issue_count,
                "generated_task_count": generated_count,
            }
        except Exception as exc:
            data_quality_dao.mark_batch_failed(
                scan_batch_id=scan_batch_id,
                scanned_rows=scanned_rows,
                error_message=str(exc),
                finished_at=_now_text(),
            )
            raise

    def _detect_internal_gaps(
        self,
        market_rows: list[dict],
        calendar_rows: list[dict],
        scan_batch_id: str,
        detected_at: str,
        options: MarketGapFillRunOptions,
    ) -> list:
        eligible_rows = [
            row
            for row in market_rows
            if row.get("exchange") in {Exchange.SH, Exchange.SZ}
            and row.get("asset_type") in ELIGIBLE_ASSET_TYPES
            and _matches_asset(row, options)
        ]
        calendar_by_key = {
            (row.get("exchange"), row.get("calendar_date")): row
            for row in calendar_rows
        }
        issues = calendar_rules._scan_missing_trading_day_bar(
            eligible_rows,
            calendar_by_key,
            scan_batch_id,
            detected_at,
        )
        return [
            item
            for item in issues
            if _matches_date(item.trade_date, options)
        ]

    def _detect_zero_and_front_history_gaps(
        self,
        market_rows: list[dict],
        calendar_rows: list[dict],
        target_date: str,
        scan_batch_id: str,
        detected_at: str,
        budget: int,
        options: MarketGapFillRunOptions,
    ) -> list:
        calendar_by_exchange = _open_dates_by_exchange(calendar_rows, target_date)
        trade_dates_by_asset = _trade_dates_by_asset(market_rows)
        issues = []

        for asset in meta_dao.get_active_assets():
            if len(issues) >= budget:
                break
            asset_code = asset.get("asset_code")
            exchange = asset.get("exchange")
            asset_type = asset.get("asset_type")
            if (
                not asset_code
                or exchange not in {Exchange.SH, Exchange.SZ}
                or asset_type not in ELIGIBLE_ASSET_TYPES
                or (options.asset_code and asset_code != options.asset_code)
            ):
                continue

            target_start = asset.get("listing_date") or DATA_COLLECTION_DEFAULT_START_DATE
            state = market_gap_fill_dao.get_asset_state(asset_code)
            known_dates = trade_dates_by_asset.get(asset_code, set())
            earliest_known = min(known_dates) if known_dates else None
            earliest_generated = state.get("earliest_generated_date")
            window_end = self._resolve_window_end(
                target_date=target_date,
                earliest_known=earliest_known,
                earliest_generated=earliest_generated,
            )
            if not window_end or window_end < target_start:
                continue

            open_dates = [
                date
                for date in reversed(calendar_by_exchange.get(exchange, []))
                if target_start <= date <= window_end
                and date not in known_dates
                and _matches_date(date, options)
            ]
            selected_dates = open_dates[:MARKET_GAP_FILL_ZERO_HISTORY_DAYS_PER_ASSET]
            selected_dates = selected_dates[: max(0, budget - len(issues))]
            if not selected_dates:
                continue

            try:
                route_source_id, route_source_code = router.get_best_source(
                    asset_code,
                    asset_type,
                    "daily_bar",
                )
            except Exception:
                route_source_id, route_source_code = None, None

            for missing_date in selected_dates:
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
                            "calendar_date": missing_date,
                            "listing_date": asset.get("listing_date"),
                            "target_start_date": target_start,
                            "route_source_id": route_source_id,
                            "route_source_code": route_source_code,
                            "missing_reason": (
                                "zero_or_front_history_without_market_row"
                            ),
                        },
                        asset_code=asset_code,
                        trade_date=missing_date,
                        source_id=None,
                    )
                )
            market_gap_fill_dao.upsert_asset_state(
                asset_code=asset_code,
                target_start_date=target_start,
                earliest_generated_date=min(selected_dates),
            )

        return issues

    @staticmethod
    def _resolve_window_end(
        target_date: str,
        earliest_known: str | None,
        earliest_generated: str | None,
    ) -> str | None:
        if earliest_generated:
            return _previous_date(earliest_generated)
        if earliest_known:
            return _previous_date(earliest_known)
        return target_date


def _open_dates_by_exchange(
    calendar_rows: list[dict],
    target_date: str,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in calendar_rows:
        if row.get("is_open") != 1:
            continue
        calendar_date = row.get("calendar_date")
        exchange = row.get("exchange")
        if not calendar_date or not exchange or calendar_date > target_date:
            continue
        result.setdefault(exchange, []).append(calendar_date)
    for dates in result.values():
        dates.sort()
    return result


def _trade_dates_by_asset(market_rows: list[dict]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in market_rows:
        asset_code = row.get("asset_code")
        trade_date = row.get("trade_date")
        if asset_code and trade_date:
            result.setdefault(asset_code, set()).add(trade_date)
    return result


def _matches_asset(row: dict, options: MarketGapFillRunOptions) -> bool:
    return not options.asset_code or row.get("asset_code") == options.asset_code


def _matches_date(
    trade_date: str | None,
    options: MarketGapFillRunOptions,
) -> bool:
    if not trade_date:
        return False
    if options.start_date and trade_date < options.start_date:
        return False
    if options.end_date and trade_date > options.end_date:
        return False
    return True


def _previous_date(date_text: str) -> str:
    date_value = datetime.strptime(date_text, "%Y-%m-%d").date()
    return (date_value - timedelta(days=1)).strftime("%Y-%m-%d")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


market_gap_scanner = MarketGapScanner()
