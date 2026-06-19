from __future__ import annotations

from datetime import datetime

from config.constants import AssetType, Exchange
from core.market_gap_fill.models import MarketGapFillRunOptions
from core.data_quality.rules import calendar_rules
from dao.data_quality_dao import data_quality_dao
from dao.market_gap_fill_dao import market_gap_fill_dao
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


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


market_gap_scanner = MarketGapScanner()
