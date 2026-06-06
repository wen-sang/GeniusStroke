from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional
from uuid import uuid4

from core.corporate_action.confirm_service import corporate_action_confirm_service
from core.corporate_action.derived_records import (
    clear_derived_records,
    insert_audit_log,
    run_rebuilds,
)
from core.corporate_action.models import CorporateActionCreateRequest, CorporateActionPreviewRequest
from core.corporate_action.service import corporate_action_service
from core.db_engine import db_engine
from dao.asset_dao import asset_dao
from dao.corporate_action_dao import corporate_action_dao
from utils.decimal_utils import quantize_exchange_qty
from utils.validators import ValidationError


@dataclass
class StockCorporateActionRequest:
    account_id: int = 1
    asset_code: str = ""
    event_type: str = ""
    record_date: str = ""
    ex_date: str = ""
    cash_pay_date: Optional[str] = None
    remark: str = ""
    cash_base_unit: Optional[str] = None
    cash_base_qty: Optional[float] = None
    cash_amount: Optional[float] = None
    tax_mode: Optional[str] = None
    ratio_from: Optional[int] = None
    ratio_to: Optional[int] = None
    share_change_subtype: Optional[str] = None


class StockCorporateActionService:
    VALID_EVENT_TYPES = {"CASH_DIVIDEND", "SHARE_CHANGE", "CASH_AND_SHARE_CHANGE"}

    def preview_stock_action(self, request: StockCorporateActionRequest) -> Dict:
        normalized = self._normalize_request(request)
        self._validate_request(normalized)
        self._ensure_stock_asset(normalized.asset_code)

        child_requests = self._build_child_requests(normalized)
        previews: Dict[str, Dict] = {}
        for child_request in child_requests:
            preview = corporate_action_service.preview_action(
                CorporateActionPreviewRequest(
                    account_id=child_request.account_id,
                    asset_code=child_request.asset_code,
                    action_type=child_request.action_type,
                    effective_date=child_request.effective_date,
                    record_date=child_request.record_date,
                    ex_date=child_request.ex_date,
                    cash_base_unit=child_request.cash_base_unit,
                    cash_base_qty=child_request.cash_base_qty,
                    cash_amount=child_request.cash_amount,
                    ratio_from=child_request.ratio_from,
                    ratio_to=child_request.ratio_to,
                    share_change_subtype=child_request.share_change_subtype,
                    tax_mode=child_request.tax_mode,
                    bundle_ref_id=child_request.bundle_ref_id,
                    reinvest_price=child_request.reinvest_price,
                    rounding_policy=child_request.rounding_policy,
                )
            )
            if child_request.action_type == "CASH_DIVIDEND":
                previews["cash"] = preview
            elif child_request.action_type == "SPLIT":
                previews["share"] = self._build_share_preview(child_request, preview)

        return {
            "event_type": normalized.event_type,
            "account_id": normalized.account_id,
            "asset_code": normalized.asset_code,
            "record_date": normalized.record_date,
            "ex_date": normalized.ex_date,
            "cash_pay_date": normalized.cash_pay_date,
            "cash": previews.get("cash"),
            "share": previews.get("share"),
        }

    def get_stock_bundle(self, bundle_ref_id: str, account_id: int) -> Dict:
        actions = self._load_bundle_actions(bundle_ref_id=bundle_ref_id, account_id=account_id)
        return {
            "bundle_ref_id": bundle_ref_id,
            "status": self._aggregate_status([action.status for action in actions]),
            "actions": [action.to_dict() for action in actions],
        }

    def update_stock_bundle(
        self,
        bundle_ref_id: str,
        account_id: int,
        request: StockCorporateActionRequest,
    ) -> Dict:
        actions = self._load_bundle_actions(bundle_ref_id=bundle_ref_id, account_id=account_id)
        normalized = self._normalize_request(request)
        self._validate_request(normalized)
        self._ensure_stock_asset(normalized.asset_code)
        self._ensure_bundle_composition_matches(actions, normalized.event_type)

        child_requests = self._build_child_requests(normalized, bundle_ref_id=bundle_ref_id)
        request_by_type = {item.action_type: item for item in child_requests}
        updated_actions = []
        with db_engine.get_connection() as conn:
            for action in actions:
                if action.status != "PENDING":
                    updated_actions.append(action)
                    continue
                child_request = request_by_type.get(action.action_type)
                if child_request is None:
                    raise ValidationError("组合事件子事件类型不匹配")
                updated = replace(
                    action,
                    effective_date=child_request.effective_date,
                    record_date=child_request.record_date,
                    ex_date=child_request.ex_date,
                    cash_base_unit=child_request.cash_base_unit,
                    cash_base_qty=child_request.cash_base_qty,
                    cash_amount=float(child_request.cash_amount) if child_request.cash_amount is not None else None,
                    ratio_from=child_request.ratio_from,
                    ratio_to=child_request.ratio_to,
                    share_change_subtype=child_request.share_change_subtype,
                    tax_mode=child_request.tax_mode,
                    remark=child_request.remark,
                    last_check_at=None,
                    last_error_message=None,
                )
                if corporate_action_dao.exists_active_business_key(
                    updated,
                    exclude_action_id=updated.action_id,
                    conn=conn,
                ):
                    raise ValidationError("相同业务键的有效股票企业事件已存在")
                corporate_action_dao.update_action(updated, conn=conn)
                updated_actions.append(updated)

        return {
            "bundle_ref_id": bundle_ref_id,
            "status": self._aggregate_status([action.status for action in updated_actions]),
            "actions": [action.to_dict() for action in updated_actions],
        }

    def confirm_stock_action(self, action_id: int, account_id: int) -> Dict:
        action = corporate_action_dao.get_action(action_id)
        if not action:
            raise ValidationError(f"企业事件不存在: {action_id}")
        if action.account_id != account_id:
            raise ValidationError("无权操作该企业事件")
        result = corporate_action_confirm_service.confirm_action(action_id)
        return {"status": self._result_status([result]), "results": [result]}

    def confirm_stock_bundle(self, bundle_ref_id: str, account_id: int) -> Dict:
        if not bundle_ref_id:
            raise ValidationError("组合事件关联号不能为空")
        actions = corporate_action_dao.list_actions_by_bundle(
            bundle_ref_id=bundle_ref_id,
            account_id=account_id,
        )
        if not actions:
            raise ValidationError(f"组合事件不存在: {bundle_ref_id}")

        results: List[Dict] = []
        for action in actions:
            if action.status == "PENDING":
                results.append(corporate_action_confirm_service.confirm_action(action.action_id or 0))
            else:
                results.append(
                    {
                        "action_id": action.action_id,
                        "result": "skipped",
                        "reason": f"status={action.status}",
                    }
                )

        refreshed = corporate_action_dao.list_actions_by_bundle(
            bundle_ref_id=bundle_ref_id,
            account_id=account_id,
        )
        return {
            "bundle_ref_id": bundle_ref_id,
            "status": self._aggregate_status([action.status for action in refreshed]),
            "results": results,
        }

    def cancel_stock_bundle(self, bundle_ref_id: str, account_id: int, remark: str = "") -> Dict:
        if not bundle_ref_id:
            raise ValidationError("组合事件关联号不能为空")

        with db_engine.get_connection() as conn:
            actions = corporate_action_dao.list_actions_by_bundle(
                bundle_ref_id=bundle_ref_id,
                account_id=account_id,
                conn=conn,
            )
            if not actions:
                raise ValidationError(f"组合事件不存在: {bundle_ref_id}")

            rebuild_from_dates: List[str] = []
            cancelled_actions = []
            for action in actions:
                if action.status == "CANCELLED":
                    cancelled_actions.append(action)
                    continue
                if action.status == "CONFIRMED":
                    clear_derived_records(action_id=action.action_id or 0, conn=conn)
                    rebuild_from_dates.append(action.effective_date)

                action.status = "CANCELLED"
                action.remark = remark or action.remark
                corporate_action_dao.update_action(action, conn=conn)
                insert_audit_log(
                    account_id=action.account_id,
                    action_type=f"CORP_CANCEL_{action.action_type}",
                    amount_change=0.0,
                    remark=f"CANCEL stock corporate action #{action.action_id}",
                    conn=conn,
                )
                cancelled_actions.append(action)

            rebuild_from = min(rebuild_from_dates) if rebuild_from_dates else ""
            if rebuild_from:
                run_rebuilds(account_id=account_id, effective_date=rebuild_from, conn=conn)

        return {
            "bundle_ref_id": bundle_ref_id,
            "status": self._aggregate_status([action.status for action in cancelled_actions]),
            "rebuild_from": rebuild_from,
            "actions": [action.to_dict() for action in cancelled_actions],
        }

    def create_stock_action(self, request: StockCorporateActionRequest) -> Dict:
        normalized = self._normalize_request(request)
        self._validate_request(normalized)
        self._ensure_stock_asset(normalized.asset_code)

        child_requests = self._build_child_requests(normalized)
        with db_engine.get_connection() as conn:
            for child_request in child_requests:
                action_key = self._request_to_action_key(child_request)
                if corporate_action_dao.exists_active_business_key(action_key, conn=conn):
                    raise ValidationError("相同业务键的有效股票企业事件已存在")
            actions = [
                corporate_action_service._create_action_in_conn(
                    child_request,
                    conn,
                    skip_duplicate_check=True,
                )
                for child_request in child_requests
            ]

        return {
            "bundle_ref_id": child_requests[0].bundle_ref_id,
            "status": self._aggregate_status([action.status for action in actions]),
            "actions": [action.to_dict() for action in actions],
        }

    def _build_child_requests(
        self,
        request: StockCorporateActionRequest,
        bundle_ref_id: Optional[str] = None,
    ) -> List[CorporateActionCreateRequest]:
        if bundle_ref_id is None and request.event_type == "CASH_AND_SHARE_CHANGE":
            bundle_ref_id = self._new_bundle_ref_id(request)

        child_requests: List[CorporateActionCreateRequest] = []
        if request.event_type in {"CASH_DIVIDEND", "CASH_AND_SHARE_CHANGE"}:
            child_requests.append(
                self._normalize_child_request(
                    CorporateActionCreateRequest(
                        account_id=request.account_id,
                        asset_code=request.asset_code,
                        action_type="CASH_DIVIDEND",
                        effective_date=request.cash_pay_date or "",
                        record_date=request.record_date,
                        ex_date=request.ex_date,
                        cash_base_unit=request.cash_base_unit,
                        cash_base_qty=request.cash_base_qty,
                        cash_amount=request.cash_amount,
                        tax_mode=request.tax_mode or "DEFERRED_STOCK_DIVIDEND",
                        bundle_ref_id=bundle_ref_id,
                        remark=request.remark,
                    )
                )
            )
        if request.event_type in {"SHARE_CHANGE", "CASH_AND_SHARE_CHANGE"}:
            child_requests.append(
                self._normalize_child_request(
                    CorporateActionCreateRequest(
                        account_id=request.account_id,
                        asset_code=request.asset_code,
                        action_type="SPLIT",
                        effective_date=request.ex_date,
                        record_date=request.record_date,
                        ex_date=request.ex_date,
                        ratio_from=request.ratio_from,
                        ratio_to=request.ratio_to,
                        share_change_subtype=request.share_change_subtype,
                        bundle_ref_id=bundle_ref_id,
                        remark=request.remark,
                    )
                )
            )
        return child_requests

    @staticmethod
    def _normalize_child_request(
        request: CorporateActionCreateRequest,
    ) -> CorporateActionCreateRequest:
        normalized = corporate_action_service._normalize_create_request(request)
        corporate_action_service._validate_request(normalized)
        return normalized

    @staticmethod
    def _request_to_action_key(request: CorporateActionCreateRequest):
        from core.corporate_action.models import CorporateAction

        return CorporateAction(
            account_id=request.account_id,
            asset_code=request.asset_code,
            action_type=request.action_type,
            effective_date=request.effective_date,
            record_date=request.record_date,
            ex_date=request.ex_date,
            cash_base_unit=request.cash_base_unit,
            cash_base_qty=request.cash_base_qty,
            cash_amount=float(request.cash_amount) if request.cash_amount is not None else None,
            ratio_from=request.ratio_from,
            ratio_to=request.ratio_to,
            share_change_subtype=request.share_change_subtype,
            tax_mode=request.tax_mode,
            reinvest_price=float(request.reinvest_price) if request.reinvest_price is not None else None,
            rounding_policy=request.rounding_policy,
        )

    def _normalize_request(
        self,
        request: StockCorporateActionRequest,
    ) -> StockCorporateActionRequest:
        return StockCorporateActionRequest(
            account_id=request.account_id,
            asset_code=(request.asset_code or "").strip(),
            event_type=(request.event_type or "").upper(),
            record_date=(request.record_date or "").strip(),
            ex_date=(request.ex_date or "").strip(),
            cash_pay_date=(request.cash_pay_date or "").strip() or None,
            remark=(request.remark or "").strip(),
            cash_base_unit=(request.cash_base_unit or "").upper() or None,
            cash_base_qty=request.cash_base_qty,
            cash_amount=request.cash_amount,
            tax_mode=(request.tax_mode or "").upper() or None,
            ratio_from=request.ratio_from,
            ratio_to=request.ratio_to,
            share_change_subtype=(request.share_change_subtype or "").upper() or None,
        )

    def _validate_request(self, request: StockCorporateActionRequest) -> None:
        if request.account_id <= 0:
            raise ValidationError("账户 ID 必须大于 0")
        if not request.asset_code:
            raise ValidationError("股票代码不能为空")
        if request.event_type not in self.VALID_EVENT_TYPES:
            raise ValidationError(f"不支持的股票企业事件类型: {request.event_type}")
        if not request.record_date:
            raise ValidationError("股权登记日不能为空")
        if not request.ex_date:
            raise ValidationError("除权除息日不能为空")

        if request.event_type in {"CASH_DIVIDEND", "CASH_AND_SHARE_CHANGE"}:
            if not request.cash_pay_date:
                raise ValidationError("现金到账日不能为空")
            if request.cash_pay_date < request.record_date:
                raise ValidationError("现金到账日不能早于股权登记日")

        if request.event_type in {"SHARE_CHANGE", "CASH_AND_SHARE_CHANGE"}:
            if request.ex_date < request.record_date:
                raise ValidationError("除权除息日不能早于股权登记日")
            if not request.ratio_from or not request.ratio_to:
                raise ValidationError("股份变动必须填写变动前后比例")
            if request.ratio_to <= request.ratio_from:
                raise ValidationError("本期股票股份变动只支持增加股份")

    @staticmethod
    def _ensure_stock_asset(asset_code: str) -> None:
        asset = asset_dao.get_asset(asset_code)
        if not asset:
            raise ValidationError(f"资产不存在: {asset_code}")
        if (asset.get("asset_type") or "").upper() != "STOCK":
            raise ValidationError("股票除权除息入口仅支持 STOCK 资产")

    @staticmethod
    def _load_bundle_actions(bundle_ref_id: str, account_id: int):
        if not bundle_ref_id:
            raise ValidationError("组合事件关联号不能为空")
        actions = corporate_action_dao.list_actions_by_bundle(
            bundle_ref_id=bundle_ref_id,
            account_id=account_id,
        )
        if not actions:
            raise ValidationError(f"组合事件不存在: {bundle_ref_id}")
        return actions

    @staticmethod
    def _ensure_bundle_composition_matches(actions, event_type: str) -> None:
        existing_types = {action.action_type for action in actions}
        expected_types = {
            "CASH_DIVIDEND": {"CASH_DIVIDEND"},
            "SHARE_CHANGE": {"SPLIT"},
            "CASH_AND_SHARE_CHANGE": {"CASH_DIVIDEND", "SPLIT"},
        }.get(event_type, set())
        if existing_types != expected_types:
            raise ValidationError("组合事件类型不可变")

    @staticmethod
    def _new_bundle_ref_id(request: StockCorporateActionRequest) -> str:
        date_text = request.ex_date.replace("-", "")
        suffix = uuid4().hex[:8].upper()
        return f"CA_BUNDLE_{request.account_id}_{request.asset_code}_{date_text}_{suffix}"

    @staticmethod
    def _aggregate_status(statuses: List[str]) -> str:
        if all(status == "PENDING" for status in statuses):
            return "PENDING"
        if all(status == "CONFIRMED" for status in statuses):
            return "CONFIRMED"
        if all(status == "CANCELLED" for status in statuses):
            return "CANCELLED"
        return "PARTIAL"

    @staticmethod
    def _result_status(results: List[Dict]) -> str:
        if all(result.get("result") == "confirmed" for result in results):
            return "CONFIRMED"
        if any(result.get("result") == "failed" for result in results):
            return "FAILED"
        return "SKIPPED"

    @staticmethod
    def _build_share_preview(
        request: CorporateActionCreateRequest,
        preview: Dict,
    ) -> Dict:
        eligible_qty = quantize_exchange_qty(preview["eligible_qty"])
        ratio_from = request.ratio_from or 1
        ratio_to = request.ratio_to or 1
        adjusted_qty = quantize_exchange_qty(eligible_qty * ratio_to / ratio_from)
        share_delta = adjusted_qty - eligible_qty
        return {
            **preview,
            "adjusted_qty": adjusted_qty,
            "share_delta": share_delta,
        }


stock_corporate_action_service = StockCorporateActionService()
