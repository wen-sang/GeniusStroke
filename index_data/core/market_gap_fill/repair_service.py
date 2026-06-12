from __future__ import annotations

import uuid
from datetime import datetime

from config import settings
from core.calculation.engine import calc_engine
from core.market_gap_fill.models import RepairStage
from core.market_return_snapshot_service import market_return_snapshot_service
from core.trade.history_rebuild_service import account_history_rebuild_service
from dao.market_dao import market_dao
from dao.market_gap_fill_dao import market_gap_fill_dao
from dao.market_gap_fill_repair_dao import market_gap_fill_repair_dao
from utils.logger import logger


class MarketGapFillRepairService:
    def run(
        self,
        sync_id: str,
        asset_code: str | None = None,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        batch_size = limit or settings.MARKET_GAP_FILL_REPAIR_BATCH_SIZE
        if dry_run:
            return {
                "claimed_assets": 0,
                "completed_assets": 0,
                "failed_assets": 0,
                "affected_accounts": 0,
                "failure_details": [],
                "dry_run": True,
            }
        run_id = "gap_repair_" + uuid.uuid4().hex
        tasks = market_gap_fill_repair_dao.claim_due(
            run_id=run_id,
            sync_id=sync_id,
            limit=batch_size,
            ttl_minutes=settings.MARKET_GAP_FILL_RUNNING_TTL_MINUTES,
            now_text=_now_text(),
            asset_code=asset_code,
        )
        summary = {
            "claimed_assets": len(tasks),
            "completed_assets": 0,
            "failed_assets": 0,
            "affected_accounts": 0,
            "failure_details": [],
        }
        target_date = market_dao.get_latest_trade_date_global()
        for task in tasks:
            try:
                detail = self._repair_task(task, target_date)
                updated = market_gap_fill_repair_dao.mark_completed(
                    repair_id=task["repair_id"],
                    run_id=run_id,
                    generation=task["generation"],
                    detail=detail,
                )
                if updated != 1:
                    raise RuntimeError("REPAIR_LEASE_LOST")
                summary["completed_assets"] += 1
                summary["affected_accounts"] += int(
                    detail["account_history"]["affected_accounts"]
                )
            except RepairStageError as exc:
                market_gap_fill_repair_dao.mark_failed(
                    repair_id=task["repair_id"],
                    run_id=run_id,
                    generation=task["generation"],
                    stage=exc.stage,
                    error_code=exc.error_code,
                    error_message=str(exc),
                    detail=exc.detail,
                )
                summary["failed_assets"] += 1
                summary["failure_details"].append(
                    {
                        "asset_code": task["asset_code"],
                        "stage": exc.stage,
                        "error_code": exc.error_code,
                        "message": str(exc)[:200],
                    }
                )
                logger.error(
                    "[MARKET_GAP_FILL][REPAIR] asset=%s stage=%s code=%s",
                    task["asset_code"],
                    exc.stage,
                    exc.error_code,
                )
            except Exception as exc:
                error_code = (
                    "REPAIR_LEASE_LOST"
                    if str(exc) == "REPAIR_LEASE_LOST"
                    else "REPAIR_FINALIZE_FAILED"
                )
                summary["failed_assets"] += 1
                summary["failure_details"].append(
                    {
                        "asset_code": task["asset_code"],
                        "stage": "finalize",
                        "error_code": error_code,
                        "message": str(exc)[:200],
                    }
                )
                logger.error(
                    "[MARKET_GAP_FILL][REPAIR] asset=%s stage=finalize code=%s",
                    task["asset_code"],
                    error_code,
                )
        return summary

    def _repair_task(self, task: dict, target_date: str | None) -> dict:
        asset_code = task["asset_code"]
        from_date = task["from_date"]
        try:
            indicator = calc_engine.rebuild_asset_from_date(
                asset_code,
                from_date,
            )
        except Exception as exc:
            raise RepairStageError(
                RepairStage.INDICATOR,
                "INDICATOR_REBUILD_FAILED",
                str(exc),
            ) from exc

        try:
            snapshot = market_return_snapshot_service.rebuild_for_asset_date_range(
                asset_code=asset_code,
                start_date=from_date,
                end_date=target_date or from_date,
            )
        except Exception as exc:
            raise RepairStageError(
                RepairStage.SNAPSHOT,
                "SNAPSHOT_REBUILD_FAILED",
                str(exc),
                {"indicator": indicator},
            ) from exc

        try:
            account_result = self._rebuild_accounts(asset_code, from_date)
        except Exception as exc:
            raise RepairStageError(
                RepairStage.ACCOUNT_HISTORY,
                "ACCOUNT_HISTORY_REBUILD_FAILED",
                str(exc),
                {
                    "indicator": indicator,
                    "snapshot": snapshot,
                },
            ) from exc
        return {
            "indicator": indicator,
            "snapshot": snapshot,
            "account_history": account_result,
        }

    @staticmethod
    def _rebuild_accounts(asset_code: str, from_date: str) -> dict:
        affected = market_gap_fill_dao.find_affected_accounts_by_asset_dates(
            {asset_code: from_date}
        )
        results = []
        for row in affected:
            result = account_history_rebuild_service.try_rebuild_history(
                account_id=int(row["account_id"]),
                from_date=row["from_date"],
            )
            message = str(result.get("message") or "")
            if "失败" in message or "行情不完整" in message:
                raise RuntimeError(message)
            results.append(
                {
                    "account_id": int(row["account_id"]),
                    "from_date": row["from_date"],
                    "updated_rows": int(result.get("updated_rows") or 0),
                    "message": message[:200],
                }
            )
        return {
            "affected_accounts": len(affected),
            "results": results,
        }


class RepairStageError(RuntimeError):
    def __init__(
        self,
        stage: str,
        error_code: str,
        message: str,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message[:200])
        self.stage = stage
        self.error_code = error_code
        self.detail = detail or {}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


market_gap_fill_repair_service = MarketGapFillRepairService()
