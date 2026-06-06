from typing import Literal, Optional

from pydantic import BaseModel, Field


ActionType = Literal["SPLIT", "CASH_DIVIDEND", "DIVIDEND_REINVEST"]
CashBaseUnit = Literal["PER_SHARE", "PER_10_SHARES", "PER_N_SHARES"]
RoundingPolicy = Literal["KEEP_DECIMAL", "ROUND_DOWN"]


class CorporateActionPreviewRequestModel(BaseModel):
    account_id: int = Field(..., gt=0, description="账户ID")
    asset_code: str = Field(..., description="资产代码")
    action_type: ActionType = Field(..., description="企业事件类型")
    effective_date: str = Field(..., description="生效日 YYYY-MM-DD")
    record_date: Optional[str] = Field(None, description="登记日 YYYY-MM-DD")
    ex_date: Optional[str] = Field(None, description="除权除息日 YYYY-MM-DD")
    cash_base_unit: Optional[CashBaseUnit] = Field(None, description="分红口径")
    cash_base_qty: Optional[float] = Field(None, gt=0, description="分红基准数量")
    cash_amount: Optional[float] = Field(None, gt=0, description="分红金额")
    ratio_from: Optional[int] = Field(None, gt=0, description="拆分前份额")
    ratio_to: Optional[int] = Field(None, gt=0, description="拆分后份额")
    share_change_subtype: Optional[str] = Field(None, description="股份变动子类型")
    tax_mode: Optional[str] = Field(None, description="税务模式")
    bundle_ref_id: Optional[str] = Field(None, description="组合事件关联号")
    reinvest_price: Optional[float] = Field(None, gt=0, description="再投价格")
    rounding_policy: Optional[RoundingPolicy] = Field(None, description="份额处理策略")


class CorporateActionCreateRequestModel(CorporateActionPreviewRequestModel):
    remark: str = Field("", description="备注")


class CorporateActionUpdateRequestModel(BaseModel):
    account_id: int = Field(..., gt=0, description="账户ID")
    effective_date: str = Field(..., description="生效日 YYYY-MM-DD")
    record_date: Optional[str] = Field(None, description="登记日 YYYY-MM-DD")
    ex_date: Optional[str] = Field(None, description="除权除息日 YYYY-MM-DD")
    cash_base_unit: Optional[CashBaseUnit] = Field(None, description="分红口径")
    cash_base_qty: Optional[float] = Field(None, gt=0, description="分红基准数量")
    cash_amount: Optional[float] = Field(None, gt=0, description="分红金额")
    ratio_from: Optional[int] = Field(None, gt=0, description="拆分前份额")
    ratio_to: Optional[int] = Field(None, gt=0, description="拆分后份额")
    share_change_subtype: Optional[str] = Field(None, description="股份变动子类型")
    tax_mode: Optional[str] = Field(None, description="税务模式")
    bundle_ref_id: Optional[str] = Field(None, description="组合事件关联号")
    reinvest_price: Optional[float] = Field(None, gt=0, description="再投价格")
    rounding_policy: Optional[RoundingPolicy] = Field(None, description="份额处理策略")
    remark: str = Field("", description="备注")


class CorporateActionCancelRequestModel(BaseModel):
    account_id: int = Field(..., gt=0, description="账户ID")
    remark: str = Field("", description="作废备注")


class CorporateActionPreviewData(BaseModel):
    eligible_qty: str
    affected_lot_count: int
    split_ratio_text: Optional[str] = None
    dividend_cash: str
    reinvest_volume: str
    dividend_cash_used: str
    cash_residual: str
    warnings: list[str] = Field(default_factory=list)


class CorporateActionPreviewResponse(BaseModel):
    success: bool
    data: CorporateActionPreviewData


class CorporateActionMutationResponse(BaseModel):
    success: bool
    message: str
    action_id: int
    status: str
    rebuild_from: str


class CorporateActionDetailData(BaseModel):
    action_id: int
    account_id: int
    asset_code: str
    action_type: str
    effective_date: str
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
    status: str
    remark: str
    source_type: str
    source_ref_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    last_check_at: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    derived_summary: dict = Field(default_factory=dict)


class CorporateActionDetailResponse(BaseModel):
    success: bool
    data: CorporateActionDetailData
