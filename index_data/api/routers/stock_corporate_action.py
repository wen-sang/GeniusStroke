from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.error_helpers import raise_validation_http_error
from core.corporate_action.stock_service import (
    StockCorporateActionRequest,
    stock_corporate_action_service,
)
from utils.validators import ValidationError


router = APIRouter(prefix="/api/stock-corporate-actions", tags=["stock_corporate_actions"])


class StockCorporateActionRequestModel(BaseModel):
    account_id: int = Field(..., gt=0, description="账户ID")
    asset_code: str = Field(..., description="股票代码")
    event_type: Literal["CASH_DIVIDEND", "SHARE_CHANGE", "CASH_AND_SHARE_CHANGE"] = Field(
        ...,
        description="股票企业事件类型",
    )
    record_date: str = Field(..., description="股权登记日 YYYY-MM-DD")
    ex_date: str = Field(..., description="除权除息日 YYYY-MM-DD")
    cash_pay_date: Optional[str] = Field(None, description="现金到账日 YYYY-MM-DD")
    remark: str = Field("", description="备注")
    cash_base_unit: Optional[Literal["PER_SHARE", "PER_10_SHARES", "PER_N_SHARES"]] = Field(
        None,
        description="分红口径",
    )
    cash_base_qty: Optional[float] = Field(None, gt=0, description="分红基准数量")
    cash_amount: Optional[float] = Field(None, gt=0, description="分红金额")
    tax_mode: Optional[str] = Field(None, description="税务模式")
    ratio_from: Optional[int] = Field(None, gt=0, description="变动前份额基数")
    ratio_to: Optional[int] = Field(None, gt=0, description="变动后份额基数")
    share_change_subtype: Optional[str] = Field(None, description="股份变动子类型")


class StockCorporateActionResponse(BaseModel):
    success: bool
    bundle_ref_id: Optional[str] = None
    status: str
    actions: list[dict]


class StockCorporateActionPreviewResponse(BaseModel):
    success: bool
    data: dict


class StockCorporateActionConfirmRequestModel(BaseModel):
    account_id: int = Field(..., gt=0, description="账户ID")


class StockCorporateActionCancelRequestModel(BaseModel):
    account_id: int = Field(..., gt=0, description="账户ID")
    remark: str = Field("", description="作废备注")


class StockCorporateActionConfirmResponse(BaseModel):
    success: bool
    status: str
    results: list[dict]
    bundle_ref_id: Optional[str] = None


class StockCorporateActionCancelResponse(BaseModel):
    success: bool
    bundle_ref_id: str
    status: str
    rebuild_from: str
    actions: list[dict]


@router.post("/preview", response_model=StockCorporateActionPreviewResponse)
async def preview_stock_corporate_action(req: StockCorporateActionRequestModel):
    try:
        result = stock_corporate_action_service.preview_stock_action(
            StockCorporateActionRequest(**req.model_dump())
        )
        return StockCorporateActionPreviewResponse(success=True, data=result)
    except ValidationError as exc:
        raise_validation_http_error("股票除权除息预览校验失败 detail=%s", exc)


@router.post("", response_model=StockCorporateActionResponse)
async def create_stock_corporate_action(req: StockCorporateActionRequestModel):
    try:
        result = stock_corporate_action_service.create_stock_action(
            StockCorporateActionRequest(**req.model_dump())
        )
        return StockCorporateActionResponse(success=True, **result)
    except ValidationError as exc:
        raise_validation_http_error("股票除权除息保存校验失败 detail=%s", exc)


@router.get("/bundles/{bundle_ref_id}", response_model=StockCorporateActionResponse)
async def get_stock_corporate_action_bundle(
    bundle_ref_id: str,
    account_id: int,
):
    try:
        result = stock_corporate_action_service.get_stock_bundle(
            bundle_ref_id=bundle_ref_id,
            account_id=account_id,
        )
        return StockCorporateActionResponse(success=True, **result)
    except ValidationError as exc:
        raise_validation_http_error("股票组合事件查询校验失败 detail=%s", exc)


@router.put("/bundles/{bundle_ref_id}", response_model=StockCorporateActionResponse)
async def update_stock_corporate_action_bundle(
    bundle_ref_id: str,
    req: StockCorporateActionRequestModel,
):
    try:
        result = stock_corporate_action_service.update_stock_bundle(
            bundle_ref_id=bundle_ref_id,
            account_id=req.account_id,
            request=StockCorporateActionRequest(**req.model_dump()),
        )
        return StockCorporateActionResponse(success=True, **result)
    except ValidationError as exc:
        raise_validation_http_error("股票组合事件修改校验失败 detail=%s", exc)


@router.post("/bundles/{bundle_ref_id}/confirm", response_model=StockCorporateActionConfirmResponse)
async def confirm_stock_corporate_action_bundle(
    bundle_ref_id: str,
    req: StockCorporateActionConfirmRequestModel,
):
    try:
        result = stock_corporate_action_service.confirm_stock_bundle(
            bundle_ref_id=bundle_ref_id,
            account_id=req.account_id,
        )
        return StockCorporateActionConfirmResponse(success=True, **result)
    except ValidationError as exc:
        raise_validation_http_error("股票组合事件确认校验失败 detail=%s", exc)


@router.post("/bundles/{bundle_ref_id}/cancel", response_model=StockCorporateActionCancelResponse)
async def cancel_stock_corporate_action_bundle(
    bundle_ref_id: str,
    req: StockCorporateActionCancelRequestModel,
):
    try:
        result = stock_corporate_action_service.cancel_stock_bundle(
            bundle_ref_id=bundle_ref_id,
            account_id=req.account_id,
            remark=req.remark,
        )
        return StockCorporateActionCancelResponse(success=True, **result)
    except ValidationError as exc:
        raise_validation_http_error("股票组合事件作废校验失败 detail=%s", exc)


@router.post("/{action_id}/confirm", response_model=StockCorporateActionConfirmResponse)
async def confirm_stock_corporate_action(
    action_id: int,
    req: StockCorporateActionConfirmRequestModel,
):
    try:
        result = stock_corporate_action_service.confirm_stock_action(
            action_id=action_id,
            account_id=req.account_id,
        )
        return StockCorporateActionConfirmResponse(success=True, **result)
    except ValidationError as exc:
        raise_validation_http_error("股票企业事件确认校验失败 detail=%s", exc)
