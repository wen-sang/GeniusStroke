from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

import pandas as pd

from config import settings
from config.constants import AssetType, DataInterface, DataSource, Exchange
from core.market_gap_fill.models import MarketGapFillResult
from core.market_gap_fill.models import MarketGapFillRunOptions
from core.market_gap_fill.scanner import market_gap_scanner
from core.market_gap_fill.tdx_day_parser import get_bar_for_date
from core.market_gap_fill.tdx_vipdoc_refresh import (
    current_package_covers,
    current_package_dir,
)
from core.market_return_snapshot_service import market_return_snapshot_service
from core.source_code_normalizer import normalize_daily_bar_source_code
from core.trade.history_rebuild_service import account_history_rebuild_service
from dao.data_quality_dao import data_quality_dao
from dao.indicator_dao import indicator_dao
from dao.market_dao import market_dao
from dao.market_gap_fill_dao import market_gap_fill_dao
from data_provider import get_data_provider
from utils.logger import logger
from utils.null_handler import handle_market_data_nulls
from utils.validators import ValidationError


class MarketGapFillService:
    """历史行情缺口回补编排服务。"""

    def run(
        self,
        target_date: str,
        options: MarketGapFillRunOptions | None = None,
    ) -> dict:
        options = options or MarketGapFillRunOptions()
        result = MarketGapFillResult()
        result.dry_run = options.dry_run
        if not settings.MARKET_GAP_FILL_ENABLED:
            return result.to_dict()

        limit = options.normalized_limit(settings.MARKET_GAP_FILL_MAX_NEW_TASKS_PER_RUN)
        if options.dry_run:
            tasks = market_gap_fill_dao.list_due_tasks(
                limit=limit,
                now_text=_now_text(),
                options=options,
            )
            result.preview_task_count = len(tasks)
            result.preview_tasks = [_task_preview(task) for task in tasks]
            return result.to_dict()

        scan_result = market_gap_scanner.run(target_date, options=options)
        result.scan_batch_id = scan_result["scan_batch_id"]
        result.generated_task_count = int(scan_result["generated_task_count"] or 0)

        run_id = "gap_fill_" + uuid.uuid4().hex
        tasks = market_gap_fill_dao.claim_due_tasks(
            run_id=run_id,
            limit=limit,
            running_ttl_minutes=settings.MARKET_GAP_FILL_RUNNING_TTL_MINUTES,
            now_text=_now_text(),
            options=options,
        )
        tickflow_budget = settings.TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN

        for task in tasks:
            try:
                used_tickflow = self._process_task(
                    task=task,
                    target_date=target_date,
                    result=result,
                    tickflow_budget=tickflow_budget,
                    no_external=options.no_external,
                )
                if used_tickflow:
                    tickflow_budget -= 1
                    time.sleep(settings.TICKFLOW_GAP_FILL_SLEEP_SECONDS)
            except Exception as exc:
                logger.error(
                    "[MARKET_GAP_FILL] task failed task_id=%s err=%s",
                    task.get("task_id"),
                    exc,
                    exc_info=True,
                )
                self._mark_retry_or_skip(task, "TASK_EXCEPTION", str(exc), {})
                result.failed_task_count += 1

        self._run_downstream_repairs(target_date, result)
        return result.to_dict()

    def _process_task(
        self,
        task: dict,
        target_date: str,
        result: MarketGapFillResult,
        tickflow_budget: int,
        no_external: bool = False,
    ) -> bool:
        asset_code = task["asset_code"]
        missing_date = task["missing_date"]
        if market_gap_fill_dao.has_market_row(asset_code, missing_date):
            self._mark_filled(task, DataSource.TDX, {"filled_by": "existing_row"})
            result.record_fill(asset_code, missing_date)
            return False

        source_attempts = []
        source_row = None
        if no_external:
            source_attempts.append(
                {"source": "route", "status": "skipped_external_disabled"}
            )
        else:
            source_row = self._try_original_source(task, source_attempts)
        if source_row and self._insert_row(task, source_row):
            result.record_fill(asset_code, missing_date)
            return False

        tdx_row = self._try_tdx(task, target_date, source_attempts)
        if tdx_row and self._insert_row(task, tdx_row):
            result.record_fill(asset_code, missing_date)
            return False

        if tickflow_budget <= 0:
            market_gap_fill_dao.defer_task(
                task_id=task["task_id"],
                retry_delay_minutes=settings.MARKET_GAP_FILL_RETRY_DELAY_MINUTES,
                detail={"deferred_by_budget": True, "attempts": source_attempts},
            )
            result.deferred_task_count += 1
            return False

        if no_external:
            market_gap_fill_dao.defer_task(
                task_id=task["task_id"],
                retry_delay_minutes=settings.MARKET_GAP_FILL_RETRY_DELAY_MINUTES,
                detail={
                    "deferred_by_no_external": True,
                    "attempts": source_attempts,
                },
            )
            result.deferred_task_count += 1
            return False

        tickflow_used, tickflow_row, retry_failed = self._try_tickflow(
            task,
            source_attempts,
        )
        if retry_failed:
            result.failed_task_count += 1
            return tickflow_used
        if tickflow_row and self._insert_row(task, tickflow_row):
            result.record_fill(asset_code, missing_date)
            return tickflow_used

        self._mark_skipped(
            task,
            "NO_SOURCE_DATA",
            "All applicable sources returned no complete bar",
            {"attempts": source_attempts},
        )
        result.skipped_task_count += 1
        return tickflow_used

    def _try_original_source(
        self,
        task: dict,
        source_attempts: list[dict],
    ) -> dict | None:
        source_id = task.get("route_source_id")
        if not source_id:
            source_attempts.append({"source": "route", "status": "skipped_no_route"})
            return None
        try:
            DataSource.validate_asset_route(source_id)
            row = self._fetch_provider_bar(
                source_id=source_id,
                task=task,
            )
            source_attempts.append(
                {"source": source_id, "status": "hit" if row else "empty"}
            )
            return row
        except Exception as exc:
            source_attempts.append(
                {"source": source_id, "status": "failed", "error": str(exc)}
            )
            return None

    def _try_tdx(
        self,
        task: dict,
        target_date: str,
        source_attempts: list[dict],
    ) -> dict | None:
        if not self._is_tdx_applicable(task):
            source_attempts.append({"source": "tdx", "status": "skipped_not_applicable"})
            return None
        if not current_package_covers(target_date):
            source_attempts.append({"source": "tdx", "status": "skipped_stale_or_missing"})
            return None
        try:
            bar = get_bar_for_date(
                root=current_package_dir(),
                exchange=task.get("exchange"),
                asset_code=task["asset_code"],
                asset_type=task.get("asset_type") or "",
                trade_date=task["missing_date"],
            )
            if bar and bar.volume == 0 and bar.amount == 0:
                source_attempts.append(
                    {"source": "tdx", "status": "skipped_zero_volume_amount"}
                )
                return None
            source_attempts.append(
                {"source": "tdx", "status": "hit" if bar else "empty"}
            )
            return bar.to_market_row() if bar else None
        except Exception as exc:
            source_attempts.append(
                {"source": "tdx", "status": "failed", "error": str(exc)}
            )
            return None

    def _try_tickflow(
        self,
        task: dict,
        source_attempts: list[dict],
    ) -> tuple[bool, dict | None, bool]:
        if task.get("asset_type") == AssetType.LOF:
            source_attempts.append(
                {"source": "tickflow", "status": "skipped_unsupported_lof"}
            )
            return False, None, False
        if not market_gap_fill_dao.tickflow_catalog_has_asset(task["asset_code"]):
            source_attempts.append({"source": "tickflow", "status": "skipped_not_in_catalog"})
            return False, None, False
        try:
            row = self._fetch_provider_bar(
                source_id=DataSource.TICKFLOW,
                task=task,
            )
            source_attempts.append(
                {"source": "tickflow", "status": "hit" if row else "empty"}
            )
            return True, row, False
        except Exception as exc:
            self._mark_retry_or_skip(
                task,
                "TICKFLOW_FETCH_ERROR",
                str(exc),
                {"attempts": source_attempts},
            )
            source_attempts.append(
                {"source": "tickflow", "status": "failed", "error": str(exc)}
            )
            return True, None, True

    def _fetch_provider_bar(self, source_id: str, task: dict) -> dict | None:
        asset_code = task["asset_code"]
        missing_date = task["missing_date"]
        exchange = task.get("exchange") or Exchange.SH
        asset_type = task.get("asset_type") or AssetType.STOCK
        adapter = self._get_adapter(source_id, exchange, asset_type)
        source_code = normalize_daily_bar_source_code(
            asset_code=asset_code,
            source_id=source_id,
            asset_type=asset_type,
            source_code=task.get("route_source_code"),
        )
        raw_data = adapter.fetch_raw(
            asset_code=asset_code,
            start_date=missing_date,
            end_date=missing_date,
            source_code=source_code,
            exchange=exchange,
            asset_type=asset_type,
        )
        if raw_data is None:
            return None
        if isinstance(raw_data, pd.DataFrame) and raw_data.empty:
            return None
        if isinstance(raw_data, list) and not raw_data:
            return None

        df = adapter.parse(raw_data, start_date=missing_date, end_date=missing_date)
        if df.empty:
            return None
        df["asset_code"] = asset_code
        df["source_id"] = source_id
        df["updated_at"] = _now_text()
        df = df[
            [
                "asset_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "source_id",
                "updated_at",
            ]
        ]
        df = handle_market_data_nulls(df)
        matched = df[df["trade_date"] == missing_date]
        if matched.empty:
            return None
        return matched.iloc[0].to_dict()

    @staticmethod
    def _get_adapter(source_id: str, exchange: str, asset_type: str):
        if source_id == DataSource.LIXINREN:
            return get_data_provider(
                source_id,
                interface_type=DataInterface.DAILY_BAR,
                exchange=exchange,
                asset_type=asset_type,
            )
        return get_data_provider(source_id)

    def _insert_row(self, task: dict, row: dict) -> bool:
        inserted = market_dao.insert_missing_daily_rows([row])
        if inserted <= 0:
            if market_gap_fill_dao.has_market_row(task["asset_code"], task["missing_date"]):
                self._mark_filled(
                    task,
                    row["source_id"],
                    {"filled_by": "existing_row_after_insert"},
                )
                return True
            raise ValidationError("Missing bar insert returned 0")
        self._mark_filled(task, row["source_id"], {"filled_by": row["source_id"]})
        return True

    @staticmethod
    def _is_tdx_applicable(task: dict) -> bool:
        return (
            task.get("exchange") in {Exchange.SH, Exchange.SZ}
            and task.get("asset_type") in {AssetType.STOCK, AssetType.ETF, AssetType.LOF}
        )

    def _mark_filled(self, task: dict, source_id: str, detail: dict[str, Any]) -> None:
        market_gap_fill_dao.mark_filled(task["task_id"], source_id, detail)
        self._sync_issue_status(task, "FIXED")

    def _mark_skipped(
        self,
        task: dict,
        error_code: str,
        error_message: str,
        detail: dict[str, Any],
    ) -> None:
        market_gap_fill_dao.mark_skipped(
            task["task_id"],
            error_code,
            error_message,
            detail,
        )
        self._sync_issue_status(task, "CONFIRMED")

    def _mark_retry_or_skip(
        self,
        task: dict,
        error_code: str,
        error_message: str,
        detail: dict[str, Any],
    ) -> None:
        if int(task.get("attempt_count") or 0) + 1 >= int(task.get("max_attempts") or 3):
            self._mark_skipped(task, error_code, error_message, detail)
            return
        market_gap_fill_dao.mark_failed_retry(
            task_id=task["task_id"],
            error_code=error_code,
            error_message=error_message,
            retry_delay_minutes=settings.MARKET_GAP_FILL_RETRY_DELAY_MINUTES,
            detail=detail,
        )

    @staticmethod
    def _sync_issue_status(task: dict, issue_status: str) -> None:
        issue_id = task.get("latest_issue_id")
        if issue_id:
            data_quality_dao.update_issue_status(int(issue_id), issue_status)

    def _run_downstream_repairs(
        self,
        target_date: str,
        result: MarketGapFillResult,
    ) -> None:
        if not result.min_filled_date_by_code:
            result.account_history_rebuild = {
                "affected_account_count": 0,
                "success": 0,
                "failed": 0,
                "details": [],
            }
            return
        for asset_code, min_date in result.min_filled_date_by_code.items():
            indicator_dao.delete_asset_from_date(asset_code, min_date)
            market_return_snapshot_service.rebuild_for_asset_date_range(
                asset_code=asset_code,
                start_date=min_date,
                end_date=target_date,
            )
        result.account_history_rebuild = self._rebuild_affected_account_history(
            result.min_filled_date_by_code
        )

    def _rebuild_affected_account_history(
        self,
        min_filled_date_by_code: dict[str, str],
    ) -> dict:
        affected_rows = market_gap_fill_dao.find_affected_accounts_by_asset_dates(
            min_filled_date_by_code
        )
        from_date_by_account: dict[int, str] = {}
        codes_by_account: dict[int, set[str]] = {}
        for row in affected_rows:
            account_id = int(row["account_id"])
            from_date = row["from_date"]
            current = from_date_by_account.get(account_id)
            if current is None or from_date < current:
                from_date_by_account[account_id] = from_date
            codes_by_account.setdefault(account_id, set()).add(row["asset_code"])

        summary = {
            "affected_account_count": len(from_date_by_account),
            "success": 0,
            "failed": 0,
            "details": [],
        }
        for account_id, from_date in sorted(from_date_by_account.items()):
            history_result = account_history_rebuild_service.try_rebuild_history(
                account_id=account_id,
                from_date=from_date,
            )
            message = str(history_result.get("message", ""))
            success = "成功" in message or int(history_result.get("updated_rows") or 0) > 0
            if success:
                summary["success"] += 1
            else:
                summary["failed"] += 1
            summary["details"].append(
                {
                    "account_id": account_id,
                    "from_date": from_date,
                    "asset_codes": sorted(codes_by_account.get(account_id, set())),
                    "result": history_result,
                }
            )
        return summary


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _task_preview(task: dict) -> dict:
    return {
        "task_id": task.get("task_id"),
        "asset_code": task.get("asset_code"),
        "missing_date": task.get("missing_date"),
        "status": task.get("status"),
        "attempt_count": task.get("attempt_count"),
        "next_retry_at": task.get("next_retry_at"),
    }


market_gap_fill_service = MarketGapFillService()
