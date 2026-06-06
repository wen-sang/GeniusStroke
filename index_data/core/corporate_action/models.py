from dataclasses import dataclass
from typing import Optional


@dataclass
class CorporateAction:
    action_id: Optional[int] = None
    account_id: int = 1
    asset_code: str = ""
    action_type: str = ""
    effective_date: str = ""
    record_date: Optional[str] = None
    ex_date: Optional[str] = None
    cash_base_unit: Optional[str] = None
    cash_base_qty: Optional[float] = None
    cash_amount: Optional[float] = None
    ratio_from: Optional[int] = None
    ratio_to: Optional[int] = None
    share_change_subtype: Optional[str] = None
    tax_mode: Optional[str] = None
    bundle_ref_id: Optional[str] = None
    reinvest_price: Optional[float] = None
    rounding_policy: Optional[str] = None
    status: str = "PENDING"
    remark: str = ""
    source_type: str = "MANUAL"
    source_ref_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    last_check_at: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "account_id": self.account_id,
            "asset_code": self.asset_code,
            "action_type": self.action_type,
            "effective_date": self.effective_date,
            "record_date": self.record_date,
            "ex_date": self.ex_date,
            "cash_base_unit": self.cash_base_unit,
            "cash_base_qty": self.cash_base_qty,
            "cash_amount": self.cash_amount,
            "ratio_from": self.ratio_from,
            "ratio_to": self.ratio_to,
            "share_change_subtype": self.share_change_subtype,
            "tax_mode": self.tax_mode,
            "bundle_ref_id": self.bundle_ref_id,
            "reinvest_price": self.reinvest_price,
            "rounding_policy": self.rounding_policy,
            "status": self.status,
            "remark": self.remark,
            "source_type": self.source_type,
            "source_ref_id": self.source_ref_id,
            "confirmed_at": self.confirmed_at,
            "last_check_at": self.last_check_at,
            "last_error_message": self.last_error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CorporateAction":
        return cls(
            action_id=data.get("action_id"),
            account_id=data.get("account_id", 1),
            asset_code=data.get("asset_code", ""),
            action_type=data.get("action_type", ""),
            effective_date=data.get("effective_date", ""),
            record_date=data.get("record_date"),
            ex_date=data.get("ex_date"),
            cash_base_unit=data.get("cash_base_unit"),
            cash_base_qty=data.get("cash_base_qty"),
            cash_amount=data.get("cash_amount"),
            ratio_from=data.get("ratio_from"),
            ratio_to=data.get("ratio_to"),
            share_change_subtype=data.get("share_change_subtype"),
            tax_mode=data.get("tax_mode"),
            bundle_ref_id=data.get("bundle_ref_id"),
            reinvest_price=data.get("reinvest_price"),
            rounding_policy=data.get("rounding_policy"),
            status=data.get("status", "PENDING"),
            remark=data.get("remark", ""),
            source_type=data.get("source_type", "MANUAL"),
            source_ref_id=data.get("source_ref_id"),
            confirmed_at=data.get("confirmed_at"),
            last_check_at=data.get("last_check_at"),
            last_error_message=data.get("last_error_message"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class CorporateActionCreateRequest:
    account_id: int = 1
    asset_code: str = ""
    action_type: str = ""
    effective_date: str = ""
    record_date: Optional[str] = None
    ex_date: Optional[str] = None
    cash_base_unit: Optional[str] = None
    cash_base_qty: Optional[float] = None
    cash_amount: Optional[float] = None
    ratio_from: Optional[int] = None
    ratio_to: Optional[int] = None
    share_change_subtype: Optional[str] = None
    tax_mode: Optional[str] = None
    bundle_ref_id: Optional[str] = None
    reinvest_price: Optional[float] = None
    rounding_policy: Optional[str] = None
    remark: str = ""


@dataclass
class CorporateActionUpdateRequest:
    action_id: int = 0
    account_id: int = 1
    effective_date: str = ""
    record_date: Optional[str] = None
    ex_date: Optional[str] = None
    cash_base_unit: Optional[str] = None
    cash_base_qty: Optional[float] = None
    cash_amount: Optional[float] = None
    ratio_from: Optional[int] = None
    ratio_to: Optional[int] = None
    share_change_subtype: Optional[str] = None
    tax_mode: Optional[str] = None
    bundle_ref_id: Optional[str] = None
    reinvest_price: Optional[float] = None
    rounding_policy: Optional[str] = None
    remark: str = ""


@dataclass
class CorporateActionPreviewRequest:
    account_id: int = 1
    asset_code: str = ""
    action_type: str = ""
    effective_date: str = ""
    record_date: Optional[str] = None
    ex_date: Optional[str] = None
    cash_base_unit: Optional[str] = None
    cash_base_qty: Optional[float] = None
    cash_amount: Optional[float] = None
    ratio_from: Optional[int] = None
    ratio_to: Optional[int] = None
    share_change_subtype: Optional[str] = None
    tax_mode: Optional[str] = None
    bundle_ref_id: Optional[str] = None
    reinvest_price: Optional[float] = None
    rounding_policy: Optional[str] = None


@dataclass
class CorporateActionLedgerRow:
    row_kind: str = "corporate_action"
    row_id: int = 0
    biz_date: str = ""
    asset_code: str = ""
    asset_name: str = ""
    display_type: str = ""
    display_amount: Optional[str] = None
    display_volume: Optional[str] = None
    display_price: Optional[str] = None
    remark: str = ""
    status: str = "PENDING"
    source_type: str = "MANUAL"
    editable_via: str = "corporate_action"
