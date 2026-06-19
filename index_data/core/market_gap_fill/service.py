from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timedelta
from typing import Callable

from config import settings
from config.constants import AssetType
from core.market_gap_fill.history_discovery import (
    MarketHistoryDiscoveryService,
)
from core.market_gap_fill.models import GapFillRunStatus
from core.market_gap_fill.models import MarketGapFillResult
from core.market_gap_fill.models import MarketGapFillRunOptions
from core.market_gap_fill.repair_service import market_gap_fill_repair_service
from core.market_gap_fill.scanner import market_gap_scanner
from core.market_gap_fill.governance import market_gap_fill_governance
from dao.data_quality_dao import data_quality_dao
from dao.market_gap_fill_dao import market_gap_fill_dao
from dao.tickflow_gap_fill_runtime_dao import tickflow_gap_fill_runtime_dao
from data_provider.tdx_vipdoc_provider import TdxPackageLockTimeout
from data_provider.tdx_vipdoc_provider import TdxVipdocProvider
from data_provider.tickflow_adapter import TickFlowAdapter
from data_provider.tickflow_adapter import TickFlowCallConfig
from data_provider.tickflow_adapter import TickFlowGapFillError
from utils.logger import logger


class MarketGapFillService:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = datetime.now,
        sleeper: Callable[[float], None] = time.sleep,
        tdx_provider: TdxVipdocProvider | None = None,
        tickflow_adapter: TickFlowAdapter | None = None,
    ) -> None:
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleeper = sleeper
        self.tdx_provider = tdx_provider or TdxVipdocProvider(
            clock=clock,
            sleeper=sleeper,
        )
        self.tickflow_adapter = tickflow_adapter or TickFlowAdapter(
            call_config=TickFlowCallConfig(
                timeout_seconds=settings.TICKFLOW_GAP_FILL_TIMEOUT_SECONDS,
                max_retries=settings.TICKFLOW_GAP_FILL_MAX_RETRIES,
                adjust="none",
                count_limit=settings.TICKFLOW_KLINE_COUNT_LIMIT,
            )
        )

    def run(
        self,
        target_date: str,
        options: MarketGapFillRunOptions | None = None,
        progress_callback=None,
    ) -> dict:
        options = options or MarketGapFillRunOptions()
        started = self.clock()
        sync_id = "gap_fill_" + uuid.uuid4().hex
        result = self._new_result(target_date, options)
        if not settings.MARKET_GAP_FILL_ENABLED:
            result.timing["total_seconds"] = self.clock() - started
            return result.to_dict()

        if options.dry_run:
            tasks = market_gap_fill_dao.list_due_tasks(
                limit=options.normalized_limit(
                    settings.MARKET_GAP_FILL_MAX_TASKS_PER_RUN
                ),
                now_text=self._now_text(),
                options=options,
            )
            result.dry_run = True
            result.preview_task_count = len(tasks)
            result.preview_tasks = [_task_preview(task) for task in tasks]
            result.timing["total_seconds"] = self.clock() - started
            return result.to_dict()

        candidates = []
        tdx_histories = {}
        gate_started = self.clock()
        try:
            with self.tdx_provider.package_lock() as lock_wait:
                result.gate["lock_wait_seconds"] = round(lock_wait, 3)
                gate = self.tdx_provider.validate_gate(target_date)
                result.gate.update(gate)
                result.timing["gate_seconds"] = self.clock() - gate_started
                if gate["status"] != "READY":
                    result.status = GapFillRunStatus.SKIPPED_TDX_NOT_READY
                else:
                    reconciled = (
                        market_gap_fill_dao.reconcile_existing_market_rows(
                            asset_code=options.asset_code
                        )
                    )
                    for item in reconciled:
                        result.record_fill(
                            item["asset_code"],
                            item["missing_date"],
                        )
                    result.tasks["filled"] += len(reconciled)
                    discovery = MarketHistoryDiscoveryService(
                        tdx_provider=self.tdx_provider,
                        wall_clock=self.wall_clock,
                    ).run_tdx(
                        target_date=target_date,
                        package_id=gate["package_id"],
                        run_id=sync_id,
                        options=options,
                    )
                    tdx_histories = discovery.pop("_histories")
                    result.history_discovery["tdx_processed_assets"] = (
                        discovery["processed_assets"]
                    )
                    result.metadata_reconciliation.update(
                        {
                            "corrected_assets":
                                discovery["corrected_assets"],
                            "conflict_assets":
                                discovery["conflict_assets"],
                            "details": discovery["details"],
                        }
                    )
                    for asset_code, dates in discovery[
                        "filled_dates_by_asset"
                    ].items():
                        for trade_date in dates:
                            result.record_fill(asset_code, trade_date)
                    result.tasks["filled"] += discovery["filled_tasks"]
                    candidates = self._run_tdx_phase(
                        target_date,
                        sync_id,
                        options,
                        result,
                        progress_callback,
                        tdx_histories,
                    )
        except TdxPackageLockTimeout:
            result.gate.update(
                {
                    "status": "BUSY",
                    "skip_reason": "TDX_PACKAGE_LOCK_TIMEOUT",
                }
            )
            result.status = GapFillRunStatus.SKIPPED_TDX_BUSY
            result.timing["gate_seconds"] = self.clock() - gate_started

        if result.gate["status"] == "READY":
            tickflow_started = self.clock()
            discovery = MarketHistoryDiscoveryService(
                tdx_provider=self.tdx_provider,
                wall_clock=self.wall_clock,
                clock=self.clock,
                sleeper=self.sleeper,
                tickflow_adapter=self.tickflow_adapter,
            ).run_tickflow(
                target_date=target_date,
                run_id=sync_id,
                options=options,
            )
            result.tickflow["requested_assets"] = discovery[
                "requested_assets"
            ]
            result.tickflow["filled_tasks"] = discovery["filled_tasks"]
            result.history_discovery.update(
                {
                    "tickflow_pending_assets":
                        discovery["pending_assets"],
                    "tickflow_completed_assets":
                        discovery["completed_assets"],
                    "tickflow_failed_assets":
                        discovery["failed_assets"],
                }
            )
            for asset_code, dates in discovery[
                "filled_dates_by_asset"
            ].items():
                for trade_date in dates:
                    result.record_fill(asset_code, trade_date)
            result.tasks["filled"] += discovery["filled_tasks"]
            governed = market_gap_fill_governance.classify_claimed_groups(
                candidates,
                run_id=sync_id,
                no_external=options.no_external,
            )
            result.tasks["filled"] += governed["filled"]
            result.tasks["confirmed"] += governed["confirmed"]
            result.tasks["failed"] += governed["failed"]
            result.tasks["deferred"] += governed["pending"]
            result.tasks["lease_lost"] += governed["lease_lost"]
            result.failed_task_count += governed["failed"]
            result.deferred_task_count += governed["pending"]
            result.timing["tickflow_seconds"] = (
                self.clock() - tickflow_started
            )

        downstream_started = self.clock()
        _progress(progress_callback, 85, None, "执行下游资产修复")
        result.downstream = market_gap_fill_repair_service.run(sync_id=sync_id)
        result.account_history_rebuild = {
            "affected_account_count": result.downstream["affected_accounts"],
            "success": result.downstream["completed_assets"],
            "failed": result.downstream["failed_assets"],
            "details": result.downstream["failure_details"],
        }
        result.timing["downstream_seconds"] = (
            self.clock() - downstream_started
        )
        self._finalize_result(result, started)
        _progress(progress_callback, 100, None, "历史行情缺口治理完成")
        logger.info(
            "[MARKET_GAP_FILL][COMPLETED] status=%s generated=%s "
            "claimed=%s filled=%s failed=%s skipped=%s deferred=%s",
            result.status,
            result.tasks["generated"],
            result.tasks["claimed"],
            result.tasks["filled"],
            result.tasks["failed"],
            result.tasks["skipped"],
            result.tasks["deferred"],
        )
        return result.to_dict()

    def _run_tdx_phase(
        self,
        target_date: str,
        run_id: str,
        options: MarketGapFillRunOptions,
        result: MarketGapFillResult,
        progress_callback,
        tdx_histories: dict[str, dict],
    ) -> list[dict]:
        scan_started = self.clock()
        _progress(progress_callback, 10, None, "扫描历史行情缺口")
        scan_result = market_gap_scanner.run(target_date, options=options)
        result.scan_batch_id = scan_result["scan_batch_id"]
        result.generated_task_count = int(
            scan_result["generated_task_count"] or 0
        )
        result.tasks["generated"] = result.generated_task_count
        config_signature = self._tickflow_config_signature()
        if options.force_tickflow_retry and options.asset_code:
            market_gap_fill_dao.force_reopen_asset(
                asset_code=options.asset_code,
                start_date=options.start_date,
                end_date=options.end_date,
            )
        result.timing["scan_seconds"] = self.clock() - scan_started

        tdx_started = self.clock()
        candidates = []
        total_claimed = 0
        processed_assets = 0
        file_error_assets = 0
        package_id = result.gate["package_id"]
        while total_claimed < settings.MARKET_GAP_FILL_MAX_TASKS_PER_RUN:
            remaining = (
                settings.MARKET_GAP_FILL_MAX_TASKS_PER_RUN - total_claimed
            )
            groups = market_gap_fill_dao.claim_due_task_groups(
                run_id=run_id,
                batch_size=settings.MARKET_GAP_FILL_CLAIM_BATCH_SIZE,
                max_tasks=remaining,
                running_ttl_minutes=
                    settings.MARKET_GAP_FILL_RUNNING_TTL_MINUTES,
                now_text=self._now_text(),
                options=options,
            )
            if not groups:
                break
            for group in groups:
                tasks = group["tasks"]
                total_claimed += len(tasks)
                result.tasks["claimed"] += len(tasks)
                if not self._renew_group(tasks, run_id):
                    result.tasks["lease_lost"] += len(tasks)
                    continue
                existing = [
                    task for task in tasks
                    if market_gap_fill_dao.has_market_row(
                        task["asset_code"],
                        task["missing_date"],
                    )
                ]
                pending = [task for task in tasks if task not in existing]
                filled = list(existing)
                rows_by_date = {}
                detail_by_date = {
                    task["missing_date"]: {
                        "final_reason": "existing_row",
                    }
                    for task in existing
                }
                if pending:
                    history = tdx_histories.get(group["asset_code"]) or {}
                    valid = history.get("valid") or {}
                    zero_dates = set(history.get("zero_dates") or [])
                    invalid_dates = set(
                        history.get("invalid_dates") or []
                    )
                    tdx_result = {
                        "file_status": history.get(
                            "file_status", "missing"
                        ),
                        "date_results": {},
                    }
                    for task in pending:
                        trade_date = task["missing_date"]
                        if trade_date in valid:
                            date_result = {
                                "status": "hit",
                                "bar": valid[trade_date],
                            }
                        elif trade_date in zero_dates:
                            date_result = {"status": "zero", "bar": None}
                        elif trade_date in invalid_dates:
                            date_result = {"status": "invalid", "bar": None}
                        else:
                            date_result = {"status": "empty", "bar": None}
                        tdx_result["date_results"][trade_date] = date_result
                    processed_assets += 1
                    result.tdx["processed_assets"] += 1
                    result.tdx["processed_tasks"] += len(pending)
                    if tdx_result["file_status"] == "missing":
                        result.tdx["file_missing_assets"] += 1
                        file_error_assets += 1
                    elif tdx_result["file_status"] == "invalid":
                        result.tdx["file_invalid_assets"] += 1
                        file_error_assets += 1
                    for task in pending:
                        date_result = tdx_result["date_results"].get(
                            task["missing_date"],
                            {"status": "empty", "bar": None},
                        )
                        status = date_result["status"]
                        if status == "hit":
                            filled.append(task)
                            rows_by_date[task["missing_date"]] = (
                                date_result["bar"]
                            )
                            detail_by_date[task["missing_date"]] = {
                                "final_reason": "tdx",
                                "tdx_package_id": package_id,
                            }
                            result.tdx["filled_tasks"] += 1
                        elif status == "zero":
                            result.tdx["zero_tasks"] += 1
                        else:
                            result.tdx["empty_tasks"] += 1
                if filled:
                    if not self._renew_group(tasks, run_id):
                        result.tasks["lease_lost"] += len(tasks)
                        continue
                    try:
                        completed = market_gap_fill_dao.commit_filled_group(
                            tasks=filled,
                            rows_by_date=rows_by_date,
                            run_id=run_id,
                            detail_by_date=detail_by_date,
                        )
                    except Exception as exc:
                        self._fail_group(
                            filled,
                            run_id,
                            "MARKET_TRANSACTION_FAILED",
                            str(exc),
                            result,
                            config_signature,
                            count_tickflow=False,
                        )
                        completed = []
                    for item in completed:
                        result.record_fill(
                            group["asset_code"],
                            item["trade_date"],
                        )
                    result.tasks["filled"] += len(completed)
                remaining_tasks = [
                    task for task in pending
                    if task not in filled
                ]
                if remaining_tasks:
                    candidates.append(
                        {
                            "exchange": group["exchange"],
                            "asset_code": group["asset_code"],
                            "tasks": remaining_tasks,
                        }
                    )
                result.tasks["processed"] += len(tasks)
                if (
                    processed_assets
                    >= settings.TDX_GAP_FILL_HEALTH_MIN_ASSETS
                    and file_error_assets / processed_assets
                    >= settings.TDX_GAP_FILL_HEALTH_ERROR_RATIO
                ):
                    result.tdx["health_breaker_triggered"] = True
            if total_claimed >= settings.MARKET_GAP_FILL_MAX_TASKS_PER_RUN:
                break
        result.timing["tdx_seconds"] = self.clock() - tdx_started
        return candidates

    def _run_tickflow_phase(
        self,
        candidates: list[dict],
        run_id: str,
        options: MarketGapFillRunOptions,
        result: MarketGapFillResult,
        run_started: float,
        progress_callback,
    ) -> None:
        result.tickflow["candidate_assets"] = len(candidates)
        config_signature = self._tickflow_config_signature()
        catalog_version = market_gap_fill_dao.get_tickflow_catalog_version()
        budget = settings.TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN
        for index, group in enumerate(candidates):
            tasks = group["tasks"]
            result.tickflow["budget_remaining"] = budget
            _progress(
                progress_callback,
                60,
                f"{index}/{len(candidates)}",
                f"TickFlow 历史补采，剩余预算 {budget}",
            )
            defer_code = self._tickflow_defer_code(
                options,
                result,
                budget,
                run_started,
            )
            if defer_code:
                self._defer_group(tasks, run_id, defer_code, result)
                continue
            if not self._renew_group(tasks, run_id):
                result.tasks["lease_lost"] += len(tasks)
                continue

            cooling_tasks = [
                task for task in tasks
                if task.get("tickflow_retry_after")
                and task["tickflow_retry_after"] > self._now_text()
            ]
            if cooling_tasks:
                for cooling_task in cooling_tasks:
                    self._skip_group(
                        [cooling_task],
                        run_id,
                        "NO_SOURCE_DATA",
                        "TickFlow no-data cooldown is still active",
                        result,
                        issue_status="CONFIRMED",
                        catalog_version=catalog_version,
                        config_signature=config_signature,
                        retry_after=cooling_task["tickflow_retry_after"],
                    )
                tasks = [
                    task for task in tasks
                    if task not in cooling_tasks
                ]
                if not tasks:
                    continue

            asset_type = tasks[0].get("asset_type")
            if asset_type == AssetType.LOF:
                self._skip_group(
                    tasks,
                    run_id,
                    "SKIPPED_UNSUPPORTED_LOF",
                    "TickFlow does not support LOF",
                    result,
                    issue_status="CONFIRMED",
                    catalog_version=catalog_version,
                    config_signature=config_signature,
                )
                continue
            catalog_status = market_gap_fill_dao.get_tickflow_catalog_status(
                group["asset_code"]
            )
            if catalog_status != "active":
                code = (
                    "SKIPPED_NOT_IN_CATALOG"
                    if catalog_status == "absent"
                    else "SKIPPED_INACTIVE_CATALOG"
                )
                self._skip_group(
                    tasks,
                    run_id,
                    code,
                    f"TickFlow catalog status: {catalog_status}",
                    result,
                    issue_status="CONFIRMED",
                    catalog_version=catalog_version,
                    config_signature=config_signature,
                )
                continue

            reservation = self._reserve_tickflow_request(
                run_started,
                config_signature,
            )
            if reservation.get("deadline_reached"):
                result.tickflow["deadline_reached"] = True
                self._defer_group(
                    tasks,
                    run_id,
                    "TICKFLOW_DEADLINE",
                    result,
                )
                continue
            if reservation.get("breaker_open"):
                result.tickflow["breaker_triggered"] = True
                result.tickflow["breaker_reason"] = reservation.get(
                    "breaker_reason"
                )
                self._defer_group(
                    tasks,
                    run_id,
                    "TICKFLOW_BREAKER_OPEN",
                    result,
                )
                continue

            budget -= 1
            result.tickflow["requested_assets"] += 1
            result.tickflow["budget_remaining"] = budget
            try:
                response = self.tickflow_adapter.fetch_daily_range(
                    asset_code=group["asset_code"],
                    exchange=group["exchange"],
                    start_date=min(task["missing_date"] for task in tasks),
                    end_date=max(task["missing_date"] for task in tasks),
                )
            except TickFlowGapFillError as exc:
                breaker = tickflow_gap_fill_runtime_dao.record_error(
                    exc.category,
                    self._now_text(microseconds=True),
                    config_signature,
                )
                if breaker["breaker_open"]:
                    result.tickflow["breaker_triggered"] = True
                    result.tickflow["breaker_reason"] = exc.category
                self._fail_group(
                    tasks,
                    run_id,
                    exc.category,
                    str(exc),
                    result,
                    config_signature,
                )
                continue

            tickflow_gap_fill_runtime_dao.record_success()
            hits = []
            invalid = []
            no_data = []
            rows_by_date = {}
            details = {}
            for task in tasks:
                date_result = response.get(task["missing_date"])
                if date_result and date_result["status"] == "hit":
                    hits.append(task)
                    rows_by_date[task["missing_date"]] = date_result["bar"]
                    details[task["missing_date"]] = {
                        "final_reason": "tickflow",
                    }
                elif date_result and date_result["status"] == "invalid":
                    invalid.append(task)
                else:
                    no_data.append(task)
            if hits:
                if self._renew_group(tasks, run_id):
                    try:
                        completed = market_gap_fill_dao.commit_filled_group(
                            tasks=hits,
                            rows_by_date=rows_by_date,
                            run_id=run_id,
                            detail_by_date=details,
                        )
                    except Exception as exc:
                        self._fail_group(
                            hits,
                            run_id,
                            "MARKET_TRANSACTION_FAILED",
                            str(exc),
                            result,
                            config_signature,
                        )
                        completed = []
                    for item in completed:
                        result.record_fill(
                            group["asset_code"],
                            item["trade_date"],
                        )
                    result.tickflow["filled_tasks"] += len(completed)
                    result.tasks["filled"] += len(completed)
                else:
                    result.tasks["lease_lost"] += len(tasks)
                    continue
            if invalid:
                breaker = tickflow_gap_fill_runtime_dao.record_error(
                    "INVALID_RESPONSE",
                    self._now_text(microseconds=True),
                    config_signature,
                )
                if breaker["breaker_open"]:
                    result.tickflow["breaker_triggered"] = True
                    result.tickflow["breaker_reason"] = "INVALID_RESPONSE"
                self._fail_group(
                    invalid,
                    run_id,
                    "INVALID_RESPONSE",
                    "TickFlow returned invalid daily bar",
                    result,
                    config_signature,
                )
            if no_data:
                retry_after = (
                    self.wall_clock()
                    + timedelta(
                        days=settings.TICKFLOW_GAP_FILL_NO_DATA_COOLDOWN_DAYS
                    )
                ).strftime("%Y-%m-%d %H:%M:%S")
                self._skip_group(
                    no_data,
                    run_id,
                    "NO_SOURCE_DATA",
                    "TickFlow returned no target date bar",
                    result,
                    issue_status="CONFIRMED",
                    catalog_version=catalog_version,
                    config_signature=config_signature,
                    retry_after=retry_after,
                )
                result.tickflow["no_data_tasks"] += len(no_data)

    def _reserve_tickflow_request(
        self,
        run_started: float,
        config_signature: str,
    ) -> dict:
        while True:
            elapsed = self.clock() - run_started
            if elapsed >= settings.TICKFLOW_GAP_FILL_MAX_SECONDS:
                return {"deadline_reached": True}
            reservation = (
                tickflow_gap_fill_runtime_dao.reserve_request_start(
                    now_text=self._now_text(microseconds=True),
                    interval_seconds=settings.TICKFLOW_GAP_FILL_SLEEP_SECONDS,
                    config_signature=config_signature,
                )
            )
            wait_seconds = float(reservation.get("wait_seconds") or 0)
            if wait_seconds <= 0:
                return reservation
            if (
                elapsed + wait_seconds
                >= settings.TICKFLOW_GAP_FILL_MAX_SECONDS
            ):
                return {"deadline_reached": True}
            self.sleeper(wait_seconds)

    def _tickflow_defer_code(
        self,
        options: MarketGapFillRunOptions,
        result: MarketGapFillResult,
        budget: int,
        run_started: float,
    ) -> str | None:
        if options.no_external:
            return "TICKFLOW_DISABLED_BY_CLI"
        if not settings.TICKFLOW_GAP_FILL_ENABLED:
            return "TICKFLOW_DISABLED"
        if result.tdx["health_breaker_triggered"]:
            return "TDX_HEALTH_BREAKER"
        if budget <= 0:
            return "TICKFLOW_BUDGET_EXHAUSTED"
        if self.clock() - run_started >= settings.TICKFLOW_GAP_FILL_MAX_SECONDS:
            result.tickflow["deadline_reached"] = True
            return "TICKFLOW_DEADLINE"
        return None

    def _renew_group(self, tasks: list[dict], run_id: str) -> bool:
        updated = market_gap_fill_dao.renew_group_lease(
            task_ids=[task["task_id"] for task in tasks],
            run_id=run_id,
            running_ttl_minutes=
                settings.MARKET_GAP_FILL_RUNNING_TTL_MINUTES,
            now_text=self._now_text(),
        )
        return updated == len(tasks)

    def _defer_group(
        self,
        tasks: list[dict],
        run_id: str,
        error_code: str,
        result: MarketGapFillResult,
    ) -> None:
        for task in tasks:
            updated = market_gap_fill_dao.defer_task(
                task_id=task["task_id"],
                run_id=run_id,
                retry_delay_minutes=
                    settings.MARKET_GAP_FILL_RETRY_DELAY_MINUTES,
                error_code=error_code,
                detail={"deferred_reason": error_code},
            )
            if updated == 1:
                result.deferred_task_count += 1
                result.tasks["deferred"] += 1
            else:
                result.tasks["lease_lost"] += 1

    def _skip_group(
        self,
        tasks: list[dict],
        run_id: str,
        error_code: str,
        error_message: str,
        result: MarketGapFillResult,
        issue_status: str,
        catalog_version: str,
        config_signature: str,
        retry_after: str | None = None,
    ) -> None:
        for task in tasks:
            updated = market_gap_fill_dao.mark_skipped(
                task_id=task["task_id"],
                run_id=run_id,
                error_code=error_code,
                error_message=error_message,
                detail={"final_reason": error_code},
                last_tdx_package_id=result.gate.get("package_id"),
                last_tickflow_catalog_version=catalog_version,
                last_tickflow_config_signature=config_signature,
                tickflow_retry_after=retry_after,
            )
            if updated == 1:
                result.skipped_task_count += 1
                result.tasks["skipped"] += 1
                self._sync_issue(task, issue_status)
            else:
                result.tasks["lease_lost"] += 1

    def _fail_group(
        self,
        tasks: list[dict],
        run_id: str,
        error_code: str,
        error_message: str,
        result: MarketGapFillResult,
        config_signature: str,
        count_tickflow: bool = True,
    ) -> None:
        for task in tasks:
            next_attempt = int(task.get("attempt_count") or 0) + 1
            max_attempts = int(task.get("max_attempts") or 3)
            updated = market_gap_fill_dao.mark_failed_retry(
                task_id=task["task_id"],
                run_id=run_id,
                error_code=(
                    "RETRY_EXHAUSTED"
                    if next_attempt >= max_attempts
                    else error_code
                ),
                error_message=error_message,
                retry_delay_minutes=
                    settings.MARKET_GAP_FILL_RETRY_DELAY_MINUTES,
                detail={"last_failure": error_code},
            )
            if updated == 1:
                result.failed_task_count += 1
                result.tasks["failed"] += 1
                if count_tickflow:
                    result.tickflow["failed_tasks"] += 1
                self._sync_issue(task, "OPEN")
            else:
                result.tasks["lease_lost"] += 1

    @staticmethod
    def _sync_issue(task: dict, status: str) -> None:
        if task.get("latest_issue_id"):
            data_quality_dao.update_issue_status(
                int(task["latest_issue_id"]),
                status,
            )

    def _new_result(
        self,
        target_date: str,
        options: MarketGapFillRunOptions,
    ) -> MarketGapFillResult:
        result = MarketGapFillResult()
        result.dry_run = options.dry_run
        result.gate["target_date"] = target_date
        result.tickflow["enabled"] = (
            settings.TICKFLOW_GAP_FILL_ENABLED
            and not options.no_external
        )
        result.tickflow["budget_total"] = (
            settings.TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN
        )
        result.tickflow["budget_remaining"] = (
            settings.TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN
        )
        return result

    def _finalize_result(
        self,
        result: MarketGapFillResult,
        started: float,
    ) -> None:
        result.timing["total_seconds"] = self.clock() - started
        if result.downstream["failed_assets"]:
            result.errors.extend(result.downstream["failure_details"])
        if (
            result.failed_task_count
            or result.tdx["health_breaker_triggered"]
            or result.history_discovery["tickflow_failed_assets"]
            or result.downstream["failed_assets"]
        ):
            result.status = GapFillRunStatus.COMPLETED_WITH_ERRORS
        elif result.deferred_task_count:
            result.status = GapFillRunStatus.COMPLETED_WITH_DEFERRED

    def _tickflow_config_signature(self) -> str:
        value = "|".join(
            (
                str(settings.TICKFLOW_GAP_FILL_TIMEOUT_SECONDS),
                str(settings.TICKFLOW_GAP_FILL_MAX_RETRIES),
                "none",
                str(settings.TICKFLOW_KLINE_COUNT_LIMIT),
                "key" if settings.TICKFLOW_API_KEY else "free",
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _now_text(self, microseconds: bool = False) -> str:
        timespec = "microseconds" if microseconds else "seconds"
        return self.wall_clock().isoformat(sep=" ", timespec=timespec)


def _task_preview(task: dict) -> dict:
    return {
        "task_id": task.get("task_id"),
        "asset_code": task.get("asset_code"),
        "missing_date": task.get("missing_date"),
        "status": task.get("status"),
        "attempt_count": task.get("attempt_count"),
        "next_retry_at": task.get("next_retry_at"),
    }


def _progress(callback, progress, sub_progress, detail) -> None:
    if callback:
        callback(progress, sub_progress, detail)


market_gap_fill_service = MarketGapFillService()
