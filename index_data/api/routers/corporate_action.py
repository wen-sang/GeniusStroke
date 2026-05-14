from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.error_helpers import raise_validation_http_error
from api.models import PaginatedResponse
from api.routers.corporate_action_models import (
    CorporateActionCancelRequestModel,
    CorporateActionCreateRequestModel,
    CorporateActionDetailData,
    CorporateActionDetailResponse,
    CorporateActionMutationResponse,
    CorporateActionPreviewData,
    CorporateActionPreviewRequestModel,
    CorporateActionPreviewResponse,
    CorporateActionUpdateRequestModel,
)
from core.corporate_action import (
    CorporateActionCreateRequest,
    CorporateActionPreviewRequest,
    CorporateActionUpdateRequest,
    corporate_action_service,
)
from utils.validators import ValidationError

router = APIRouter(prefix="/api/corporate-actions", tags=["corporate_actions"])


def _normalize_preview_data(payload: dict) -> CorporateActionPreviewData:
    return CorporateActionPreviewData(
        eligible_qty=str(payload.get("eligible_qty")),
        affected_lot_count=int(payload.get("affected_lot_count") or 0),
        split_ratio_text=payload.get("split_ratio_text"),
        dividend_cash=str(payload.get("dividend_cash")),
        reinvest_volume=str(payload.get("reinvest_volume")),
        dividend_cash_used=str(payload.get("dividend_cash_used")),
        cash_residual=str(payload.get("cash_residual")),
        warnings=list(payload.get("warnings") or []),
    )


@router.post("/preview", response_model=CorporateActionPreviewResponse)
async def preview_corporate_action(req: CorporateActionPreviewRequestModel):
    try:
        preview = corporate_action_service.preview_action(
            CorporateActionPreviewRequest(**req.model_dump())
        )
        return CorporateActionPreviewResponse(success=True, data=_normalize_preview_data(preview))
    except ValidationError as exc:
        raise_validation_http_error("企业事件预览校验失败 detail=%s", exc)


@router.get("", response_model=PaginatedResponse)
async def list_corporate_actions(
    account_id: int = Query(1, description="账户ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量"),
    asset_code: Optional[str] = Query(None, description="资产代码"),
    status: Optional[str] = Query(None, description="状态筛选"),
):
    return corporate_action_service.get_actions_page(
        account_id=account_id,
        page=page,
        page_size=page_size,
        asset_code=asset_code,
        status=status,
    )


@router.post("", response_model=CorporateActionMutationResponse)
async def create_corporate_action(req: CorporateActionCreateRequestModel):
    try:
        action = corporate_action_service.create_action(
            CorporateActionCreateRequest(**req.model_dump())
        )
        return CorporateActionMutationResponse(
            success=True,
            message="企业事件创建成功",
            action_id=int(action.action_id or 0),
            status=action.status,
            rebuild_from=action.effective_date,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{action_id}", response_model=CorporateActionMutationResponse)
async def update_corporate_action(action_id: int, req: CorporateActionUpdateRequestModel):
    try:
        action = corporate_action_service.update_action(
            CorporateActionUpdateRequest(action_id=action_id, **req.model_dump())
        )
        return CorporateActionMutationResponse(
            success=True,
            message="企业事件更新成功",
            action_id=int(action.action_id or 0),
            status=action.status,
            rebuild_from=action.effective_date,
        )
    except ValidationError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise_validation_http_error(
            "企业事件更新校验失败 action_id=%s detail=%s",
            exc,
            action_id,
            status_code=status_code,
        )


@router.post("/{action_id}/cancel", response_model=CorporateActionMutationResponse)
async def cancel_corporate_action(action_id: int, req: CorporateActionCancelRequestModel):
    try:
        action = corporate_action_service.cancel_action(
            action_id=action_id,
            account_id=req.account_id,
            remark=req.remark,
        )
        return CorporateActionMutationResponse(
            success=True,
            message="企业事件作废成功",
            action_id=int(action.action_id or 0),
            status=action.status,
            rebuild_from=action.effective_date,
        )
    except ValidationError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise_validation_http_error(
            "企业事件作废校验失败 action_id=%s detail=%s",
            exc,
            action_id,
            status_code=status_code,
        )


@router.get("/{action_id}", response_model=CorporateActionDetailResponse)
async def get_corporate_action(action_id: int):
    action = corporate_action_service.get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="企业事件不存在")

    derived_summary = {}
    if action.status == "PENDING":
        preview = corporate_action_service.preview_action(
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
        derived_summary = _normalize_preview_data(preview).model_dump()

    return CorporateActionDetailResponse(
        success=True,
        data=CorporateActionDetailData(**action.to_dict(), derived_summary=derived_summary),
    )
