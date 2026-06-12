from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any, Callable, Optional

from config import settings
from core.calculation.engine import calc_engine
from api.services.asset_catalog_service import asset_catalog_service
from core.db_engine import db_engine
from core.market_gap_fill.service import market_gap_fill_service
from core.sync_models import (
    TOTAL_SYNC_STEPS,
    SyncCallbacks,
    SyncErrorInfo,
    SyncResult,
    SyncStepLifecycle,
    SyncTaskStatus,
    build_task_id,
    format_timestamp,
    get_sync_step,
)
from core.task_manager import task_manager
from core.trade import post_market_asset_refresh_service
from dao.meta_dao import meta_dao
from utils.logger import logger, suppress_console_messages


class EnvironmentCheckError(RuntimeError):
    pass


def check_environment() -> None:
    """检查数据库连接和核心表。"""
    db_file = Path(db_engine.db_path)
    if not db_file.exists():
        logger.warning(
            f"警告: 数据库文件未找到 ({db_file})。如果是首次运行，请确保已执行初始化/迁移脚本。"
        )

    try:
        assets = meta_dao.get_active_assets()
    except Exception as exc:
        raise EnvironmentCheckError(str(exc)) from exc

    logger.info(f"   -> 数据库连接正常 (检测到 {len(assets)} 个在市标的)")


def extract_post_market_refresh_codes(
    collection_result: dict[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    gap_fill_result = collection_result.get("market_gap_fill_result") or {}
    updated_codes = sorted(
        set(collection_result.get("market_success_codes", []))
        | set(collection_result.get("fund_success_codes", []))
        | set(gap_fill_result.get("filled_codes", []))
    )
    failed_codes = sorted(
        set(collection_result.get("market_failed_codes", []))
        | set(collection_result.get("fund_failed_codes", []))
    )
    empty_codes = sorted(
        set(collection_result.get("market_empty_codes", []))
        | set(collection_result.get("fund_empty_codes", []))
    )
    return updated_codes, failed_codes, empty_codes


def run_post_market_refresh(
    collection_result: dict[str, Any],
    progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
) -> dict[str, Any]:
    updated_codes, failed_codes, empty_codes = extract_post_market_refresh_codes(collection_result)
    with suppress_console_messages(["[POST_MARKET_ASSET_REFRESH]"]):
        return post_market_asset_refresh_service.refresh_after_market_update(
            target_date=collection_result.get("target_date"),
            updated_codes=updated_codes,
            failed_codes=failed_codes,
            empty_codes=empty_codes,
            progress_callback=progress_callback,
        )


class SyncRunner:
    def __init__(
        self,
        check_environment_fn: Callable[[], None] = check_environment,
        collection_fn: Callable[[], dict[str, Any]] = task_manager.run_daily_job,
        gap_fill_fn: Optional[Callable[[str], dict[str, Any]]] = None,
        calc_fn: Callable[[], None] = calc_engine.run,
        asset_refresh_fn: Callable[[dict[str, Any]], dict[str, Any]] = run_post_market_refresh,
    ) -> None:
        self._check_environment_fn = check_environment_fn
        self._collection_fn = collection_fn
        self._gap_fill_fn = gap_fill_fn or (lambda target_date: {})
        self._calc_fn = calc_fn
        self._asset_refresh_fn = asset_refresh_fn

    def run(
        self,
        task_id: Optional[str] = None,
        callbacks: Optional[SyncCallbacks] = None,
    ) -> SyncResult:
        callbacks = callbacks or SyncCallbacks()
        started_epoch = time.time()
        started_at = format_timestamp()
        resolved_task_id = task_id or build_task_id()
        result = SyncResult(
            task_id=resolved_task_id,
            status=SyncTaskStatus.SUCCESS,
            started_at=started_at,
            summary={
                "target_date": None,
                "collection_result": {},
                "asset_refresh_summary": {},
            },
        )

        self._log_start_banner()

        collection_result: dict[str, Any] = {}
        asset_refresh_summary: dict[str, Any] = {}
        gap_fill_partial = False

        step = get_sync_step(1)
        self._start_step(step.number, callbacks)
        logger.info("[Step 1/4] 系统基础设施初始化...")
        try:
            self._check_environment_fn()
        except Exception as exc:
            logger.critical(f"环境检查失败: {exc}", exc_info=True)
            return self._finalize_failure(
                result=result,
                step_number=step.number,
                callbacks=callbacks,
                exc=exc,
                message="环境检查失败",
                recoverable=False,
                started_epoch=started_epoch,
            )
        self._complete_step(step.number, callbacks)

        step = get_sync_step(2)
        self._start_step(step.number, callbacks)
        logger.info("[Step 2/4] 启动数据采集任务 (Task Manager)...")
        try:
            catalog_sync_result = asset_catalog_service.sync_enabled_sources_with_timeout()
            collection_result = self._invoke_with_optional_progress(
                self._collection_fn,
                self._build_scaled_step_progress_callback(
                    step.number,
                    callbacks,
                    0,
                    80,
                ),
            ) or {}
            collection_result["catalog_sync_result"] = catalog_sync_result
            collection_result["market_gap_fill_result"] = self._run_market_gap_fill(
                collection_result=collection_result,
                callbacks=callbacks,
                step_number=step.number,
            )
            gap_fill_partial = (
                collection_result["market_gap_fill_result"].get("status")
                == "COMPLETED_WITH_ERRORS"
            )
        except Exception as exc:
            logger.critical(f"数据采集任务异常终止: {exc}", exc_info=True)
            return self._finalize_failure(
                result=result,
                step_number=step.number,
                callbacks=callbacks,
                exc=exc,
                message="数据采集任务异常终止",
                recoverable=False,
                started_epoch=started_epoch,
            )
        result.summary["target_date"] = collection_result.get("target_date")
        result.summary["collection_result"] = collection_result
        self._complete_step(step.number, callbacks)

        step = get_sync_step(3)
        self._start_step(step.number, callbacks)
        logger.info("[Step 3/4] 启动指标计算任务 (Calc Engine)...")
        try:
            self._invoke_with_optional_progress(
                self._calc_fn,
                self._build_step_progress_callback(step.number, callbacks),
            )
        except Exception as exc:
            logger.critical(f"指标计算任务异常终止: {exc}", exc_info=True)
            return self._finalize_failure(
                result=result,
                step_number=step.number,
                callbacks=callbacks,
                exc=exc,
                message="指标计算任务异常终止",
                recoverable=False,
                started_epoch=started_epoch,
            )
        self._complete_step(step.number, callbacks)

        step = get_sync_step(4)
        self._start_step(step.number, callbacks)
        logger.info("[Step 4/4] 账户资产更新...")
        try:
            asset_refresh_summary = self._invoke_with_optional_progress(
                self._asset_refresh_fn,
                self._build_step_progress_callback(step.number, callbacks),
                collection_result,
            ) or {}
            result.summary["asset_refresh_summary"] = asset_refresh_summary
        except Exception as exc:
            logger.error(f"采集后账户资产刷新失败: {exc}", exc_info=True)
            result.summary["asset_refresh_summary"] = asset_refresh_summary
            return self._finalize_partial_success(
                result=result,
                step_number=step.number,
                callbacks=callbacks,
                exc=exc,
                message="采集后账户资产刷新失败",
                started_epoch=started_epoch,
            )
        self._complete_step(step.number, callbacks)

        result.current_step = TOTAL_SYNC_STEPS
        result.status = (
            SyncTaskStatus.PARTIAL_SUCCESS
            if gap_fill_partial
            else SyncTaskStatus.SUCCESS
        )
        self._finalize_common(result, started_epoch)
        logger.info(f"所有任务执行完毕，总耗时: {result.elapsed_seconds:.2f} 秒")
        return result

    def _run_market_gap_fill(
        self,
        collection_result: dict[str, Any],
        callbacks: SyncCallbacks,
        step_number: int,
    ) -> dict[str, Any]:
        target_date = collection_result.get("target_date")
        if not target_date:
            return {}

        logger.info("[Step 2.5/4] 历史行情缺口治理回补...")
        try:
            return self._invoke_with_optional_progress(
                self._gap_fill_fn,
                self._build_scaled_step_progress_callback(
                    step_number,
                    callbacks,
                    80,
                    100,
                ),
                target_date,
            ) or {}
        except Exception as exc:
            logger.error("[MARKET_GAP_FILL] Step 2.5 failed: %s", exc, exc_info=True)
            return {
                "status": "COMPLETED_WITH_ERRORS",
                "filled_codes": [],
                "min_filled_date_by_code": {},
                "filled_task_count": 0,
                "failed_task_count": 0,
                "skipped_task_count": 0,
                "deferred_task_count": 0,
                "errors": [
                    {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                ],
            }

    def _log_start_banner(self) -> None:
        logger.info("========================================")
        logger.info(f"   GeniusStroke v{settings.VERSION} - 启动主程序")
        logger.info("========================================")

    def _start_step(self, step_number: int, callbacks: SyncCallbacks) -> None:
        step = get_sync_step(step_number)
        if callbacks.on_step_change:
            callbacks.on_step_change(step.number, step.name, SyncStepLifecycle.RUNNING.value)
        if callbacks.on_progress:
            callbacks.on_progress(step.number, None, None, None)

    def _complete_step(self, step_number: int, callbacks: SyncCallbacks) -> None:
        step = get_sync_step(step_number)
        if callbacks.on_step_change:
            callbacks.on_step_change(step.number, step.name, SyncStepLifecycle.COMPLETED.value)

    def _fail_step(self, step_number: int, callbacks: SyncCallbacks) -> None:
        step = get_sync_step(step_number)
        if callbacks.on_step_change:
            callbacks.on_step_change(step.number, step.name, SyncStepLifecycle.FAILED.value)

    def _finalize_common(self, result: SyncResult, started_epoch: float) -> None:
        result.finished_at = format_timestamp()
        result.elapsed_seconds = round(time.time() - started_epoch, 2)

    def _finalize_failure(
        self,
        result: SyncResult,
        step_number: int,
        callbacks: SyncCallbacks,
        exc: Exception,
        message: str,
        recoverable: bool,
        started_epoch: float,
    ) -> SyncResult:
        result.status = SyncTaskStatus.FAILED
        result.current_step = step_number
        result.failed_step = step_number
        result.error = SyncErrorInfo(
            type=type(exc).__name__,
            message=str(exc) or message,
            recoverable=recoverable,
        )
        self._fail_step(step_number, callbacks)
        self._finalize_common(result, started_epoch)
        logger.info(
            f"任务执行失败，终止于第 {step_number}/{TOTAL_SYNC_STEPS} 步，总耗时: {result.elapsed_seconds:.2f} 秒"
        )
        return result

    def _finalize_partial_success(
        self,
        result: SyncResult,
        step_number: int,
        callbacks: SyncCallbacks,
        exc: Exception,
        message: str,
        started_epoch: float,
    ) -> SyncResult:
        result.status = SyncTaskStatus.PARTIAL_SUCCESS
        result.current_step = step_number
        result.failed_step = step_number
        result.error = SyncErrorInfo(
            type=type(exc).__name__,
            message=str(exc) or message,
            recoverable=True,
        )
        self._fail_step(step_number, callbacks)
        self._finalize_common(result, started_epoch)
        logger.info(
            f"任务部分完成，第 {step_number}/{TOTAL_SYNC_STEPS} 步存在异常，总耗时: {result.elapsed_seconds:.2f} 秒"
        )
        return result

    @staticmethod
    def _build_step_progress_callback(
        step_number: int,
        callbacks: SyncCallbacks,
    ) -> Callable[[Optional[int], Optional[str], Optional[str]], None]:
        def _callback(
            progress: Optional[int] = None,
            sub_progress: Optional[str] = None,
            detail: Optional[str] = None,
        ) -> None:
            if callbacks.on_progress:
                callbacks.on_progress(step_number, progress, sub_progress, detail)

        return _callback

    @staticmethod
    def _build_scaled_step_progress_callback(
        step_number: int,
        callbacks: SyncCallbacks,
        start: int,
        end: int,
    ) -> Callable[[Optional[int], Optional[str], Optional[str]], None]:
        def _callback(
            progress: Optional[int] = None,
            sub_progress: Optional[str] = None,
            detail: Optional[str] = None,
        ) -> None:
            if not callbacks.on_progress:
                return
            scaled = None
            if progress is not None:
                bounded = min(100, max(0, int(progress)))
                scaled = start + round((end - start) * bounded / 100)
            callbacks.on_progress(
                step_number,
                scaled,
                sub_progress,
                detail,
            )

        return _callback

    @staticmethod
    def _invoke_with_optional_progress(
        fn: Callable[..., Any],
        progress_callback: Callable[[Optional[int], Optional[str], Optional[str]], None],
        *args: Any,
    ) -> Any:
        if SyncRunner._supports_progress_callback(fn):
            return fn(*args, progress_callback=progress_callback)
        return fn(*args)

    @staticmethod
    def _supports_progress_callback(fn: Callable[..., Any]) -> bool:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return False

        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                return True
            if (
                parameter.name == "progress_callback"
                and parameter.kind
                in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                )
            ):
                return True
        return False


sync_runner = SyncRunner(gap_fill_fn=market_gap_fill_service.run)
