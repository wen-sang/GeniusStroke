from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional

from core.db_engine import db_engine
from dao.trade_dao import trade_dao
from utils.decimal_utils import quantize_amount, quantize_price, to_decimal
from utils.logger import logger
from utils.validators import ValidationError

from .dao import corporate_action_dao
from .derived_records import clear_derived_records, insert_audit_log, run_rebuilds
from .models import (
    CorporateAction,
    CorporateActionCreateRequest,
    CorporateActionPreviewRequest,
    CorporateActionUpdateRequest,
)
from .preview_helpers import build_preview


class CorporateActionService:
    VALID_ACTION_TYPES = {"SPLIT", "CASH_DIVIDEND", "DIVIDEND_REINVEST"}
    VALID_CASH_BASE_UNITS = {"PER_SHARE", "PER_10_SHARES"}
    VALID_ROUNDING_POLICIES = {"KEEP_DECIMAL", "ROUND_DOWN"}

    def __init__(self) -> None:
        self.dao = corporate_action_dao
        self.trade_dao = trade_dao

    def preview_action(self, request: CorporateActionPreviewRequest) -> Dict:
        normalized = self._normalize_preview_request(request)
        self._validate_request(normalized)

        with db_engine.get_connection(readonly=True) as conn:
            return build_preview(
                account_id=normalized.account_id,
                asset_code=normalized.asset_code,
                action_type=normalized.action_type,
                effective_date=normalized.effective_date,
                cash_base_unit=normalized.cash_base_unit,
                cash_amount=normalized.cash_amount,
                ratio_from=normalized.ratio_from,
                ratio_to=normalized.ratio_to,
                reinvest_price=normalized.reinvest_price,
                rounding_policy=normalized.rounding_policy,
                conn=conn,
            )

    def create_action(self, request: CorporateActionCreateRequest) -> CorporateAction:
        normalized = self._normalize_create_request(request)
        self._validate_request(normalized)

        with db_engine.get_connection() as conn:
            self.trade_dao.get_or_create_account(normalized.account_id, conn=conn)
            if self.dao.exists_active_action(
                account_id=normalized.account_id,
                asset_code=normalized.asset_code,
                effective_date=normalized.effective_date,
                action_type=normalized.action_type,
                conn=conn,
            ):
                raise ValidationError("同一账户、标的、生效日、事件类型的有效企业事件已存在")

            preview = build_preview(
                account_id=normalized.account_id,
                asset_code=normalized.asset_code,
                action_type=normalized.action_type,
                effective_date=normalized.effective_date,
                cash_base_unit=normalized.cash_base_unit,
                cash_amount=normalized.cash_amount,
                ratio_from=normalized.ratio_from,
                ratio_to=normalized.ratio_to,
                reinvest_price=normalized.reinvest_price,
                rounding_policy=normalized.rounding_policy,
                conn=conn,
            )
            action = CorporateAction(
                account_id=normalized.account_id,
                asset_code=normalized.asset_code,
                action_type=normalized.action_type,
                effective_date=normalized.effective_date,
                record_date=normalized.record_date,
                cash_base_unit=normalized.cash_base_unit,
                cash_amount=float(normalized.cash_amount) if normalized.cash_amount is not None else None,
                ratio_from=normalized.ratio_from,
                ratio_to=normalized.ratio_to,
                reinvest_price=float(normalized.reinvest_price) if normalized.reinvest_price is not None else None,
                rounding_policy=normalized.rounding_policy,
                remark=normalized.remark,
                status="PENDING",
                source_type="MANUAL",
            )
            action.action_id = self.dao.insert_action(action, conn=conn)
            insert_audit_log(
                account_id=action.account_id,
                action_type=f"CORP_{action.action_type}",
                amount_change=float(preview["dividend_cash"]),
                remark=f"CREATE corporate action {action.action_type} #{action.action_id}",
                conn=conn,
            )

        logger.info(
            "[CORP_ACTION_CREATE] action_id=%s account_id=%s asset=%s type=%s",
            action.action_id,
            action.account_id,
            action.asset_code,
            action.action_type,
        )
        return action

    def update_action(self, request: CorporateActionUpdateRequest) -> CorporateAction:
        normalized = self._normalize_update_request(request)

        with db_engine.get_connection() as conn:
            existing = self.dao.get_action(normalized.action_id, conn=conn)
            if not existing:
                raise ValidationError(f"企业事件不存在: {normalized.action_id}")
            if existing.status != "PENDING":
                raise ValidationError("仅待确认企业事件可编辑")

            updated = replace(
                existing,
                effective_date=normalized.effective_date,
                record_date=normalized.record_date,
                cash_base_unit=normalized.cash_base_unit,
                cash_amount=float(normalized.cash_amount) if normalized.cash_amount is not None else None,
                ratio_from=normalized.ratio_from,
                ratio_to=normalized.ratio_to,
                reinvest_price=float(normalized.reinvest_price) if normalized.reinvest_price is not None else None,
                rounding_policy=normalized.rounding_policy,
                remark=normalized.remark,
            )
            self._validate_action_model(updated)
            if self.dao.exists_active_action(
                account_id=updated.account_id,
                asset_code=updated.asset_code,
                effective_date=updated.effective_date,
                action_type=updated.action_type,
                exclude_action_id=updated.action_id,
                conn=conn,
            ):
                raise ValidationError("同一账户、标的、生效日、事件类型的有效企业事件已存在")

            preview = build_preview(
                account_id=updated.account_id,
                asset_code=updated.asset_code,
                action_type=updated.action_type,
                effective_date=updated.effective_date,
                cash_base_unit=updated.cash_base_unit,
                cash_amount=to_decimal(updated.cash_amount) if updated.cash_amount is not None else None,
                ratio_from=updated.ratio_from,
                ratio_to=updated.ratio_to,
                reinvest_price=to_decimal(updated.reinvest_price) if updated.reinvest_price is not None else None,
                rounding_policy=updated.rounding_policy,
                conn=conn,
            )
            updated.last_check_at = None
            updated.last_error_message = None
            self.dao.update_action(updated, conn=conn)
            insert_audit_log(
                account_id=updated.account_id,
                action_type=f"CORP_UPDATE_{updated.action_type}",
                amount_change=float(preview["dividend_cash"]),
                remark=f"UPDATE corporate action #{updated.action_id}",
                conn=conn,
            )

        logger.info("[CORP_ACTION_UPDATE] action_id=%s", updated.action_id)
        return updated

    def cancel_action(self, action_id: int, account_id: int, remark: str = "") -> CorporateAction:
        with db_engine.get_connection() as conn:
            existing = self.dao.get_action(action_id, conn=conn)
            if not existing:
                raise ValidationError(f"企业事件不存在: {action_id}")
            if existing.account_id != account_id:
                raise ValidationError("无权操作该企业事件")
            if existing.status == "CANCELLED":
                return existing

            cancelled = replace(
                existing,
                status="CANCELLED",
                remark=remark or existing.remark,
            )
            self.dao.update_action(cancelled, conn=conn)
            if existing.status == "CONFIRMED":
                clear_derived_records(action_id=cancelled.action_id, conn=conn)
                run_rebuilds(account_id=cancelled.account_id, effective_date=cancelled.effective_date, conn=conn)
            insert_audit_log(
                account_id=cancelled.account_id,
                action_type=f"CORP_CANCEL_{cancelled.action_type}",
                amount_change=0.0,
                remark=f"CANCEL corporate action #{cancelled.action_id}",
                conn=conn,
            )

        logger.info("[CORP_ACTION_CANCEL] action_id=%s", cancelled.action_id)
        return cancelled

    def get_action(self, action_id: int) -> Optional[CorporateAction]:
        return self.dao.get_action(action_id)

    def list_actions(
        self,
        account_id: int,
        asset_code: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        return self.dao.list_actions(account_id=account_id, asset_code=asset_code, status=status)

    def get_actions_page(
        self,
        account_id: int,
        page: int = 1,
        page_size: int = 60,
        asset_code: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict:
        actions = self.dao.list_actions(account_id=account_id, asset_code=asset_code, status=status)
        total_count = len(actions)
        offset = (page - 1) * page_size
        page_items = actions[offset: offset + page_size]

        items: List[Dict] = []
        with db_engine.get_connection(readonly=True) as conn:
            for action in page_items:
                asset_name = action.get("asset_name") or self.dao.get_asset_name(action["asset_code"], conn=conn)
                items.append(
                    {
                        "row_kind": "corporate_action",
                        "row_id": int(action["action_id"]),
                        "action_id": int(action["action_id"]),
                        "account_id": int(action["account_id"]),
                        "biz_date": action["effective_date"],
                        "effective_date": action["effective_date"],
                        "record_date": action.get("record_date"),
                        "asset_code": action["asset_code"],
                        "asset_name": asset_name,
                        "action_type": action["action_type"],
                        "cash_base_unit": action.get("cash_base_unit"),
                        "cash_amount": float(action["cash_amount"]) if action.get("cash_amount") is not None else None,
                        "ratio_from": int(action["ratio_from"]) if action.get("ratio_from") is not None else None,
                        "ratio_to": int(action["ratio_to"]) if action.get("ratio_to") is not None else None,
                        "reinvest_price": float(action["reinvest_price"]) if action.get("reinvest_price") is not None else None,
                        "rounding_policy": action.get("rounding_policy"),
                        "display_type": self._display_action_type(action["action_type"]),
                        "remark": action.get("remark") or "",
                        "status": action.get("status") or "PENDING",
                        "source_type": action.get("source_type") or "MANUAL",
                        "source_ref_id": action.get("source_ref_id"),
                        "confirmed_at": action.get("confirmed_at"),
                        "last_check_at": action.get("last_check_at"),
                        "last_error_message": action.get("last_error_message"),
                        "derived_summary": self._build_action_summary(action),
                        "editable_via": "corporate_action",
                    }
                )

        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        return {
            "items": items,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_account_ledger(
        self,
        account_id: int,
        page: int = 1,
        page_size: int = 60,
    ) -> Dict:
        with db_engine.get_connection(readonly=True) as conn:
            orders = self.trade_dao.list_orders_for_ledger(account_id=account_id, conn=conn)
            actions = self.dao.list_actions(account_id=account_id, conn=conn)

            items: List[Dict] = []
            for order in orders:
                items.append(
                    {
                        "row_kind": "trade_order",
                        "row_id": int(order["order_id"]),
                        "order_id": int(order["order_id"]),
                        "biz_date": order["trade_time"][:10],
                        "trade_time": order["trade_time"],
                        "asset_code": order["asset_code"],
                        "asset_name": order.get("asset_name") or order["asset_code"],
                        "side": order["side"],
                        "price": float(order.get("price") or 0.0),
                        "volume": float(order.get("volume") or 0.0),
                        "amount": float(order.get("amount") or 0.0),
                        "commission": float(order.get("commission") or 0.0),
                        "tax": float(order.get("tax") or 0.0),
                        "realized_pnl": float(order.get("realized_pnl") or 0.0),
                        "display_type": "买入" if order["side"] == "BUY" else "卖出",
                        "display_amount": float(order.get("amount") or 0.0),
                        "display_volume": float(order.get("volume") or 0.0),
                        "display_price": float(order.get("price") or 0.0),
                        "remark": order.get("remark") or "",
                        "status": "ACTIVE" if int(order.get("status") or 0) == 1 else "CANCELLED",
                        "order_type": order.get("order_type"),
                        "source_type": order.get("source_type") or "MANUAL",
                        "editable_via": "trade",
                        "_sort_kind": 1,
                    }
                )

            for action in actions:
                asset_name = self.dao.get_asset_name(action["asset_code"], conn=conn)
                items.append(
                    {
                        "row_kind": "corporate_action",
                        "row_id": int(action["action_id"]),
                        "action_id": int(action["action_id"]),
                        "biz_date": action["effective_date"],
                        "effective_date": action["effective_date"],
                        "record_date": action.get("record_date"),
                        "asset_code": action["asset_code"],
                        "asset_name": asset_name,
                        "action_type": action["action_type"],
                        "cash_base_unit": action.get("cash_base_unit"),
                        "cash_amount": float(action["cash_amount"]) if action.get("cash_amount") is not None else None,
                        "ratio_from": int(action["ratio_from"]) if action.get("ratio_from") is not None else None,
                        "ratio_to": int(action["ratio_to"]) if action.get("ratio_to") is not None else None,
                        "reinvest_price": float(action["reinvest_price"]) if action.get("reinvest_price") is not None else None,
                        "rounding_policy": action.get("rounding_policy"),
                        "display_type": self._display_action_type(action["action_type"]),
                        "display_amount": self._display_action_amount(action),
                        "display_volume": self._display_action_volume(action),
                        "display_price": float(action["reinvest_price"]) if action.get("reinvest_price") is not None else None,
                        "remark": action.get("remark") or "",
                        "status": action.get("status") or "PENDING",
                        "source_type": action.get("source_type") or "MANUAL",
                        "editable_via": "corporate_action",
                        "_sort_kind": 0,
                    }
                )

        items.sort(key=lambda item: (item["biz_date"], -item["_sort_kind"], item["row_id"]), reverse=True)
        total_count = len(items)
        offset = (page - 1) * page_size
        paged = items[offset: offset + page_size]
        for item in paged:
            item.pop("_sort_kind", None)
        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        return {
            "items": paged,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def _normalize_preview_request(self, request: CorporateActionPreviewRequest) -> CorporateActionPreviewRequest:
        return CorporateActionPreviewRequest(
            account_id=request.account_id,
            asset_code=(request.asset_code or "").strip(),
            action_type=(request.action_type or "").upper(),
            effective_date=(request.effective_date or "").strip(),
            record_date=(request.record_date or "").strip() or None,
            cash_base_unit=(request.cash_base_unit or "").upper() or None,
            cash_amount=quantize_amount(request.cash_amount) if request.cash_amount is not None else None,
            ratio_from=request.ratio_from,
            ratio_to=request.ratio_to,
            reinvest_price=quantize_price(request.reinvest_price) if request.reinvest_price is not None else None,
            rounding_policy=(request.rounding_policy or "").upper() or None,
        )

    def _normalize_create_request(self, request: CorporateActionCreateRequest) -> CorporateActionCreateRequest:
        preview = self._normalize_preview_request(
            CorporateActionPreviewRequest(
                account_id=request.account_id,
                asset_code=request.asset_code,
                action_type=request.action_type,
                effective_date=request.effective_date,
                record_date=request.record_date,
                cash_base_unit=request.cash_base_unit,
                cash_amount=request.cash_amount,
                ratio_from=request.ratio_from,
                ratio_to=request.ratio_to,
                reinvest_price=request.reinvest_price,
                rounding_policy=request.rounding_policy,
            )
        )
        return CorporateActionCreateRequest(
            account_id=preview.account_id,
            asset_code=preview.asset_code,
            action_type=preview.action_type,
            effective_date=preview.effective_date,
            record_date=preview.record_date,
            cash_base_unit=preview.cash_base_unit,
            cash_amount=preview.cash_amount,
            ratio_from=preview.ratio_from,
            ratio_to=preview.ratio_to,
            reinvest_price=preview.reinvest_price,
            rounding_policy=preview.rounding_policy,
            remark=(request.remark or "").strip(),
        )

    def _normalize_update_request(self, request: CorporateActionUpdateRequest) -> CorporateActionUpdateRequest:
        preview = self._normalize_preview_request(
            CorporateActionPreviewRequest(
                account_id=request.account_id,
                asset_code="",
                action_type="",
                effective_date=request.effective_date,
                record_date=request.record_date,
                cash_base_unit=request.cash_base_unit,
                cash_amount=request.cash_amount,
                ratio_from=request.ratio_from,
                ratio_to=request.ratio_to,
                reinvest_price=request.reinvest_price,
                rounding_policy=request.rounding_policy,
            )
        )
        return CorporateActionUpdateRequest(
            action_id=request.action_id,
            account_id=request.account_id,
            effective_date=preview.effective_date,
            record_date=preview.record_date,
            cash_base_unit=preview.cash_base_unit,
            cash_amount=preview.cash_amount,
            ratio_from=preview.ratio_from,
            ratio_to=preview.ratio_to,
            reinvest_price=preview.reinvest_price,
            rounding_policy=preview.rounding_policy,
            remark=(request.remark or "").strip(),
        )

    def _validate_request(self, request: CorporateActionPreviewRequest) -> None:
        if request.account_id <= 0:
            raise ValidationError("账户 ID 必须大于 0")
        if not request.asset_code:
            raise ValidationError("资产代码不能为空")
        if request.action_type not in self.VALID_ACTION_TYPES:
            raise ValidationError(f"不支持的企业事件类型: {request.action_type}")
        if not request.effective_date:
            raise ValidationError("生效日不能为空")

        if request.action_type == "SPLIT":
            if not request.ratio_from or not request.ratio_to:
                raise ValidationError("份额调整必须填写拆分前后份额")
            if request.ratio_from <= 0 or request.ratio_to <= 0:
                raise ValidationError("份额调整比例必须大于 0")
            if request.ratio_from == request.ratio_to:
                raise ValidationError("份额调整前后份额不能相同")
            return

        if request.cash_base_unit not in self.VALID_CASH_BASE_UNITS:
            raise ValidationError("分红口径不合法")
        if request.cash_amount is None or request.cash_amount <= 0:
            raise ValidationError("分红金额必须大于 0")

        if request.action_type == "DIVIDEND_REINVEST":
            if request.reinvest_price is None or request.reinvest_price <= 0:
                raise ValidationError("再投价格必须大于 0")
            if request.rounding_policy not in self.VALID_ROUNDING_POLICIES:
                raise ValidationError("份额处理策略不合法")

    def _validate_action_model(self, action: CorporateAction) -> None:
        self._validate_request(
            CorporateActionPreviewRequest(
                account_id=action.account_id,
                asset_code=action.asset_code,
                action_type=action.action_type,
                effective_date=action.effective_date,
                record_date=action.record_date,
                cash_base_unit=action.cash_base_unit,
                cash_amount=action.cash_amount,
                ratio_from=action.ratio_from,
                ratio_to=action.ratio_to,
                reinvest_price=action.reinvest_price,
                rounding_policy=action.rounding_policy,
            )
        )

    def _display_action_type(self, action_type: str) -> str:
        mapping = {
            "SPLIT": "份额调整",
            "CASH_DIVIDEND": "现金分红",
            "DIVIDEND_REINVEST": "红利再投",
        }
        return mapping.get(action_type, action_type)

    def _display_action_amount(self, action: Dict) -> Optional[float]:
        cash_amount = action.get("cash_amount")
        return float(cash_amount) if cash_amount is not None else None

    def _display_action_volume(self, action: Dict) -> Optional[float]:
        if action.get("action_type") == "SPLIT":
            return None
        return None

    def _build_action_summary(self, action: Dict) -> Dict:
        summary = {
            "summary_text": self._build_action_summary_text(action),
            "status_hint": action.get("last_error_message") or "",
        }
        if action.get("action_type") == "SPLIT":
            if action.get("ratio_from") and action.get("ratio_to"):
                summary["split_ratio_text"] = f'{action["ratio_from"]}:{action["ratio_to"]}'
            else:
                summary["split_ratio_text"] = "--"
        if action.get("action_type") in {"CASH_DIVIDEND", "DIVIDEND_REINVEST"}:
            summary["cash_text"] = self._build_dividend_text(action)
        if action.get("action_type") == "DIVIDEND_REINVEST" and action.get("reinvest_price") is not None:
            summary["reinvest_price_text"] = str(action.get("reinvest_price"))
        return summary

    def _build_action_summary_text(self, action: Dict) -> str:
        if action.get("action_type") == "SPLIT":
            ratio_from = action.get("ratio_from")
            ratio_to = action.get("ratio_to")
            if ratio_from and ratio_to:
                return f"比例 {ratio_from}:{ratio_to}"
            return "比例待确认"
        if action.get("action_type") in {"CASH_DIVIDEND", "DIVIDEND_REINVEST"}:
            return self._build_dividend_text(action)
        return "--"

    @staticmethod
    def _build_dividend_text(action: Dict) -> str:
        cash_amount = action.get("cash_amount")
        if cash_amount is None:
            return "--"
        unit_text = "每10份" if action.get("cash_base_unit") == "PER_10_SHARES" else "每份"
        return f"{unit_text} {cash_amount}"


corporate_action_service = CorporateActionService()
