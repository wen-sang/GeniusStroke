# core/task_manager.py - GeniusStroke v2.2 (Final UX)
import time
import random
import datetime
import akshare as ak

# 文件: core/task_manager.py
from typing import Callable, Dict, List, Optional
from dao.meta_dao import meta_dao
from dao.market_dao import market_dao
from core.calendar import calendar_service
from core.router import router
from core.pipeline import DataPipeline
from core.fundamental.manager import fundamental_manager
from core.fund_daily_manager import fund_daily_manager
from utils.date_utils import get_current_date
from utils.logger import logger
from config.settings import (
    DATA_COLLECTION_DEFAULT_START_DATE,
    MARKET_CLOSE_HOUR,
    MARKET_UPDATE_ERROR_SLEEP_SECONDS,
    MARKET_UPDATE_NON_AKSHARE_SLEEP_SECONDS,
    SLEEP_MAX,
    SLEEP_MIN,
)
from config.constants import DataInterface, DataSource
from utils.date_utils import is_market_closed

class TaskManager:
    """
    任务调度器 (v2.2 Final UX)
    精简日志模式，聚焦状态与结果
    """
    
    def __init__(self):
        self.pipeline = DataPipeline()  # 修复：初始化 pipeline 实例

    def run_daily_job(
        self,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Dict[str, object]:
        target_date = self._prepare_target_date(progress_callback)
        if not target_date:
            return self._build_no_update_result(progress_callback)

        logger.info(f"   -> 本次更新截止日期: {target_date}")

        assets = self._load_active_assets(progress_callback)
        market_result = self._run_market_collection_phase(
            assets,
            target_date,
            progress_callback,
        )
        self._run_fundamental_phase(target_date, progress_callback)
        fund_result = self._run_fund_daily_phase(target_date, progress_callback)
        self._report_collection_completion(
            market_result,
            fund_result,
            progress_callback,
        )
        return self._build_result(
            target_date=target_date,
            market_success_codes=market_result["success_codes"],
            market_failed_codes=market_result["failed_codes"],
            market_empty_codes=market_result["empty_codes"],
            fund_success_codes=fund_result.get("success_codes", []),
            fund_failed_codes=fund_result.get("failed_codes", []),
            fund_empty_codes=fund_result.get("empty_codes", []),
        )

    def _prepare_target_date(
        self,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Optional[str]:
        self._report_progress(progress_callback, 2, "初始化交易日历")
        if self._maintain_calendar() is False:
            return None
        return self._get_target_date()

    def _build_no_update_result(
        self,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Dict[str, object]:
        logger.warning("   -> 无法确定目标日期或今日无需更新，本阶段跳过。")
        self._report_progress(progress_callback, 100, "0/0", "今日无需更新")
        return self._build_result(None)

    def _load_active_assets(
        self,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> List[dict]:
        assets = meta_dao.get_active_assets()
        logger.info(f"   -> 扫描到在市资产: {len(assets)} 个")
        self._report_progress(progress_callback, 5, f"0/{len(assets)}", "扫描待更新资产")
        return assets

    def _run_market_collection_phase(
        self,
        assets: List[dict],
        target_date: str,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Dict[str, object]:
        logger.info("   >>> [Phase 1] 核心行情更新 (OHLCV)...")
        scan_result = self._scan_market_update_tasks(assets, target_date, progress_callback)
        update_queue = scan_result["update_queue"]
        failed_codes = scan_result["failed_codes"]
        if not update_queue:
            self._log_empty_market_update_queue(target_date, failed_codes)
            self._report_progress(progress_callback, 70, "0/0", "核心行情更新完成")
            return {
                "success_codes": set(),
                "failed_codes": failed_codes,
                "empty_codes": set(),
            }
        logger.info(f"   发现 {len(update_queue)} 个标的需更新行情:")
        return self._execute_market_update_queue(update_queue, failed_codes, progress_callback)

    def _scan_market_update_tasks(
        self,
        assets: List[dict],
        target_date: str,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Dict[str, object]:
        update_queue = []
        market_failed_codes = set()
        all_codes = [asset["asset_code"] for asset in assets]
        last_dates_map = market_dao.get_last_dates_batch(all_codes)

        for index, asset in enumerate(assets, start=1):
            code = asset["asset_code"]
            try:
                task = self._build_market_update_task(asset, target_date, last_dates_map)
                if task is not None:
                    update_queue.append(task)
            except Exception as e:
                market_failed_codes.add(code)
                logger.error(f"Scan Error {code}: {e}")
            finally:
                scan_progress = 5 if not assets else min(20, 5 + round((index / len(assets)) * 15))
                self._report_progress(
                    progress_callback,
                    scan_progress,
                    f"{index}/{len(assets)}",
                    "扫描待更新资产",
                )

        return {
            "update_queue": update_queue,
            "failed_codes": market_failed_codes,
        }

    def _build_market_update_task(
        self,
        asset: dict,
        target_date: str,
        last_dates_map: Dict[str, Optional[str]],
    ) -> Optional[dict]:
        code = asset["asset_code"]
        asset_type = asset.get("asset_type", "INDEX")
        source_id, source_code = router.get_best_source(
            code,
            asset_type,
            interface=DataInterface.DAILY_BAR,
        )
        source_id = DataSource.validate_asset_route(source_id)
        start_date = self._calc_start_date(
            last_dates_map.get(code),
            asset.get("listing_date"),
        )
        if start_date > target_date:
            return None
        return {
            "code": code,
            "source_id": source_id,
            "source_code": source_code,
            "exchange": asset.get("exchange", "SH"),
            "asset_type": asset_type,
            "start_date": start_date,
            "target_date": target_date,
        }

    def _log_empty_market_update_queue(self, target_date: str, failed_codes: set) -> None:
        if failed_codes:
            logger.warning(
                f"   扫描完成: 无可执行行情更新任务，且有 {len(failed_codes)} "
                f"个标的在路由阶段失败。"
            )
            return
        logger.info(f"   扫描完成: 所有标的行情数据均已是最新 ({target_date})，无需更新。")

    def _execute_market_update_queue(
        self,
        update_queue: List[dict],
        failed_codes: set,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Dict[str, object]:
        success_codes = set()
        empty_codes = set()
        success_count = 0
        fail_count = len(failed_codes)
        empty_count = 0

        for index, task in enumerate(update_queue, start=1):
            code = task["code"]
            progress = f"[{index}/{len(update_queue)}]"
            try:
                status = self._run_single_market_update_task(task, progress)
                if status == "success":
                    success_count += 1
                    success_codes.add(code)
                elif status == "empty":
                    empty_count += 1
                    empty_codes.add(code)
                else:
                    fail_count += 1
                    failed_codes.add(code)
            except Exception as e:
                fail_count += 1
                failed_codes.add(code)
                logger.error(f"      {progress} 更新 {code} 异常: {e}")
                time.sleep(MARKET_UPDATE_ERROR_SLEEP_SECONDS)
            finally:
                queue_progress = 20 + round((index / len(update_queue)) * 50)
                self._report_progress(
                    progress_callback,
                    min(queue_progress, 70),
                    f"{index}/{len(update_queue)}",
                    f"核心行情更新: {code}",
                )

        logger.info(f"   -> Phase 1 完成: 成功 {success_count}, 空数据 {empty_count}, 失败 {fail_count}。")
        return {
            "success_codes": success_codes,
            "failed_codes": failed_codes,
            "empty_codes": empty_codes,
        }

    def _run_single_market_update_task(self, task: dict, progress: str) -> str:
        code = task["code"]
        start_date = task["start_date"]
        target_date = task["target_date"]
        source_id = task["source_id"]

        result = self.pipeline.run_task(
            code,
            source_id,
            start_date,
            target_date,
            source_code=task["source_code"],
            exchange=task["exchange"],
            asset_type=task.get("asset_type", "INDEX"),
        )
        status = result.get("status")
        if status == "success":
            logger.info(f"      {progress} 更新 {code} ({start_date} -> {target_date}) ... Success")
            self._sleep_after_market_update(source_id)
            return "success"
        if status == "empty":
            logger.warning(f"      {progress} 更新 {code} 无有效数据")
            return "empty"
        logger.warning(f"      {progress} 更新 {code} 失败 (查看日志详情)")
        return "failed"

    def _sleep_after_market_update(self, source_id: str) -> None:
        if DataSource.validate_asset_route(source_id) == DataSource.AKSHARE:
            sleep_time = random.randint(SLEEP_MIN, SLEEP_MAX)
            logger.info(f"      休眠 {sleep_time}s (AkShare限流)...")
            time.sleep(sleep_time)
            return
        time.sleep(MARKET_UPDATE_NON_AKSHARE_SLEEP_SECONDS)

    def _run_fundamental_phase(
        self,
        target_date: str,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> None:
        logger.info("   >>> [Phase 2] 基本面数据同步 (Fundamental)...")
        self._report_progress(progress_callback, 75, None, "基本面数据同步")
        try:
            fundamental_manager.run(target_date)
        except Exception as e:
            logger.error(f"   基本面模块执行失败: {e}", exc_info=True)

    def _run_fund_daily_phase(
        self,
        target_date: str,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Dict[str, object]:
        logger.info("   >>> [Phase 3] 基金净值数据同步 (Fund Daily)...")
        self._report_progress(progress_callback, 88, None, "基金净值数据同步")
        try:
            return fund_daily_manager.run(target_date)
        except Exception as e:
            logger.error(f"   净值数据模块执行失败: {e}", exc_info=True)
            return {
                "target_date": target_date,
                "success_codes": [],
                "failed_codes": [],
                "empty_codes": [],
            }

    def _report_collection_completion(
        self,
        market_result: Dict[str, object],
        fund_result: Dict[str, object],
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> None:
        logger.info("   -> 数据采集任务完成。")
        total_market = sum(
            len(market_result.get(key, []))
            for key in ("success_codes", "failed_codes", "empty_codes")
        )
        total_fund = sum(
            len(fund_result.get(key, []))
            for key in ("success_codes", "failed_codes", "empty_codes")
        )
        self._report_progress(
            progress_callback,
            100,
            f"{total_market}+{total_fund}",
            "数据采集完成",
        )

    def _build_result(
        self,
        target_date,
        market_success_codes=None,
        market_failed_codes=None,
        market_empty_codes=None,
        fund_success_codes=None,
        fund_failed_codes=None,
        fund_empty_codes=None,
    ) -> Dict[str, object]:
        return {
            "target_date": target_date,
            "market_success_codes": sorted(market_success_codes or []),
            "market_failed_codes": sorted(market_failed_codes or []),
            "market_empty_codes": sorted(market_empty_codes or []),
            "fund_success_codes": sorted(fund_success_codes or []),
            "fund_failed_codes": sorted(fund_failed_codes or []),
            "fund_empty_codes": sorted(fund_empty_codes or []),
        }

    @staticmethod
    def _report_progress(
        callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]],
        progress: Optional[int],
        sub_progress: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        if callback:
            callback(progress, sub_progress, detail)

    def _maintain_calendar(self):
        """检查并更新交易日历"""
        try:
            summary = calendar_service.sync_legacy_trade_calendar()
            logger.info(
                "   -> 交易日历兼容表检查完成 changed=%s rows=%s end=%s",
                summary["changed"],
                summary["legacy_count"],
                summary["legacy_end"],
            )
            return True
        except Exception as e:
            logger.error(f"   -> 交易日历维护失败: {e}")
            return False

    def _get_target_date(self):
        today = get_current_date()
        is_closed = is_market_closed(MARKET_CLOSE_HOUR)
        trade_days = market_dao.get_trade_calendar()
        if not trade_days:
            return None
        if is_closed and (today in trade_days):
            return today
        else:
            valid = [d for d in trade_days if d < today]
            return valid[-1] if valid else None

    def _calc_start_date(self, last_local_date, listing_date):
        if last_local_date:
            dt = datetime.datetime.strptime(last_local_date, "%Y-%m-%d")
            dt_next = dt + datetime.timedelta(days=1)
            return dt_next.strftime("%Y-%m-%d")
        else:
            if listing_date:
                return listing_date
            return DATA_COLLECTION_DEFAULT_START_DATE

task_manager = TaskManager()
