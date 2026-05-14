from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from core.db_engine import db_engine
from dao.market_dao import market_dao
from utils.logger import logger
from utils.validators import ValidationError

from .dao import corporate_action_dao
from .derived_records import rebuild_derived_records
from .models import CorporateAction
from .preview_helpers import build_preview, ensure_preview_has_eligible_holding


class CorporateActionConfirmService:
    def __init__(self) -> None:
        self.dao = corporate_action_dao

    def confirm_pending_actions(
        self,
        target_date: Optional[str] = None,
        account_ids: Optional[Sequence[int]] = None,
        asset_codes: Optional[Sequence[str]] = None,
    ) -> Dict[str, object]:
        effective_cutoff = target_date or market_dao.get_latest_trade_date_global()
        summary = {
            "target_date": effective_cutoff,
            "scanned": 0,
            "confirmed": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
        }
        if not effective_cutoff:
            return summary

        actions = self.dao.list_actions_for_confirmation(
            target_date=effective_cutoff,
            account_ids=account_ids,
            asset_codes=asset_codes,
        )
        summary["scanned"] = len(actions)
        for action in actions:
            result = self.confirm_action(action.action_id or 0, latest_market_date=effective_cutoff)
            summary["results"].append(result)
            status = result.get("result")
            if status == "confirmed":
                summary["confirmed"] += 1
            elif status == "failed":
                summary["failed"] += 1
            else:
                summary["skipped"] += 1
        return summary

    def confirm_action(self, action_id: int, latest_market_date: Optional[str] = None) -> Dict[str, object]:
        if action_id <= 0:
            return {"action_id": action_id, "result": "skipped", "reason": "invalid_action_id"}

        effective_cutoff = latest_market_date or market_dao.get_latest_trade_date_global()
        if not effective_cutoff:
            self._mark_failure(action_id, "行情表为空，无法确认企业事件")
            return {"action_id": action_id, "result": "failed", "reason": "empty_market_data"}

        try:
            with db_engine.get_connection() as conn:
                action = self.dao.get_action(action_id, conn=conn)
                if not action:
                    return {"action_id": action_id, "result": "skipped", "reason": "not_found"}
                if action.status != "PENDING":
                    return {
                        "action_id": action_id,
                        "result": "skipped",
                        "reason": f"status={action.status}",
                    }

                self._ensure_market_date_ready(action, effective_cutoff)
                self._ensure_effective_market_data(action)

                preview = build_preview(
                    account_id=action.account_id,
                    asset_code=action.asset_code,
                    action_type=action.action_type,
                    effective_date=action.effective_date,
                    cash_base_unit=action.cash_base_unit,
                    cash_amount=self._to_decimal_or_none(action.cash_amount),
                    ratio_from=action.ratio_from,
                    ratio_to=action.ratio_to,
                    reinvest_price=self._to_decimal_or_none(action.reinvest_price),
                    rounding_policy=action.rounding_policy,
                    conn=conn,
                )
                ensure_preview_has_eligible_holding(action.action_type, preview)

                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                confirmed = replace(
                    action,
                    status="CONFIRMED",
                    confirmed_at=now,
                    last_check_at=now,
                    last_error_message=None,
                )
                self.dao.update_action(confirmed, conn=conn)
                rebuild_derived_records(confirmed, preview, conn)

                from core.trade.history_rebuild_service import account_history_rebuild_service
                from core.trade.rebuild_service import account_rebuild_service

                account_rebuild_service.rebuild_current_state(
                    account_id=confirmed.account_id,
                    conn=conn,
                )
                history_result = account_history_rebuild_service.try_rebuild_history(
                    account_id=confirmed.account_id,
                    from_date=confirmed.effective_date,
                    conn=conn,
                )
                if history_result.get("message") != "账户历史重算成功":
                    raise ValidationError(str(history_result.get("message") or "账户历史重算失败"))

                live_result = account_history_rebuild_service.sync_live_snapshot(
                    account_id=confirmed.account_id,
                    biz_date=confirmed.effective_date,
                    conn=conn,
                )
                live_message = str(live_result.get("message") or "")
                if live_message not in {"账户实时快照已同步", "历史快照已覆盖当前业务日"}:
                    raise ValidationError(live_message or "live snapshot 同步失败")

            logger.info(
                "[CORP_ACTION_CONFIRM] action_id=%s account_id=%s asset=%s type=%s",
                confirmed.action_id,
                confirmed.account_id,
                confirmed.asset_code,
                confirmed.action_type,
            )
            return {
                "action_id": action_id,
                "result": "confirmed",
                "account_id": confirmed.account_id,
                "effective_date": confirmed.effective_date,
            }
        except Exception as exc:
            message = self._normalize_error_message(exc)
            self._mark_failure(action_id, message)
            logger.warning("[CORP_ACTION_CONFIRM][FAILED] action_id=%s detail=%s", action_id, message)
            return {"action_id": action_id, "result": "failed", "reason": message}

    def _mark_failure(self, action_id: int, message: str) -> None:
        with db_engine.get_connection() as conn:
            action = self.dao.get_action(action_id, conn=conn)
            if not action or action.status != "PENDING":
                return
            failed = replace(
                action,
                last_check_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_error_message=message[:500],
            )
            self.dao.update_action(failed, conn=conn)

    @staticmethod
    def _ensure_market_date_ready(action: CorporateAction, latest_market_date: str) -> None:
        if action.effective_date > latest_market_date:
            raise ValidationError("生效日收盘价或净值尚未入库")

    @staticmethod
    def _ensure_effective_market_data(action: CorporateAction) -> None:
        price_info = market_dao.get_latest_prices_batch_as_of([action.asset_code], action.effective_date)
        fund_info = market_dao.get_latest_fund_navs_batch_as_of([action.asset_code], action.effective_date)
        market_trade_date = (price_info.get(action.asset_code) or {}).get("trade_date")
        fund_trade_date = (fund_info.get(action.asset_code) or {}).get("trade_date")
        if market_trade_date == action.effective_date or fund_trade_date == action.effective_date:
            return
        raise ValidationError("生效日收盘价或净值尚未入库")

    @staticmethod
    def _normalize_error_message(exc: Exception) -> str:
        detail = str(exc).strip()
        return detail or exc.__class__.__name__

    @staticmethod
    def _to_decimal_or_none(value):
        from utils.decimal_utils import to_decimal

        if value is None:
            return None
        return to_decimal(value)


corporate_action_confirm_service = CorporateActionConfirmService()
