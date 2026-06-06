# 文件: api/routers/account.py
"""
账户管理 API 路由
v2.4.5: 支持账户汇总、入金出金
"""
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from api.routers.account_models import (
    AccountDeleteResponse,
    AccountListItem,
    AccountManageModel,
    AccountManageRequest,
    AccountManageResponse,
    AccountPerformanceResponse,
    AccountSummaryResponse,
    AdjustRequest,
    CashFlowCreateRequest,
    CashFlowResponse,
    DepositRequest,
    ImportRebuildRequest,
    ImportRebuildResponse,
    OperationResponse,
    RebuildResponse,
    WithdrawRequest,
)
from api.routers.account_route_helpers import (
    build_account_summary_response,
    build_import_rebuild_response,
    ensure_import_rebuild_access,
    extract_import_rebuild_payload,
    raise_internal_http_error,
    raise_validation_http_error,
    resolve_account_validation_status,
)
from core.trade import (
    account_history_rebuild_service,
    account_performance_service,
    account_rebuild_service,
    cash_flow_service,
    trade_service,
)
from core.trade.import_rebuild_service import account_import_rebuild_service
from utils.validators import ValidationError

router = APIRouter(prefix="/api/account", tags=["account"])

# ========== API 端点 ==========

@router.get("/list", response_model=list[AccountListItem])
async def get_account_list():
    """
    获取账户列表
    """
    try:
        accounts = trade_service.list_accounts_for_switch()
        return [AccountListItem(**item) for item in accounts]
    except Exception as exc:
        raise_internal_http_error("查询账户列表失败", "查询账户列表失败", exc)


@router.get("/summary", response_model=AccountSummaryResponse)
async def get_account_summary(account_id: int = Query(1, description="账户ID")):
    """
    获取账户汇总信息（现金、总市值、累计收益等）
    """
    summary = trade_service.get_account_summary(account_id)

    return build_account_summary_response(summary)


@router.get("/performance", response_model=AccountPerformanceResponse)
async def get_account_performance(account_id: int = Query(1, description="账户ID")):
    """获取账户绩效指标。"""
    try:
        return AccountPerformanceResponse(
            **account_performance_service.get_account_performance(account_id)
        )
    except ValidationError as exc:
        raise_validation_http_error(
            "账户绩效查询校验失败 account_id=%s detail=%s",
            exc,
            account_id,
            detail_to_status=resolve_account_validation_status,
        )
    except Exception as exc:
        raise_internal_http_error("账户绩效查询失败 account_id=%s", "账户绩效查询失败", exc, account_id)


@router.post("", response_model=AccountManageResponse)
async def create_account(req: AccountManageRequest):
    """创建账户"""
    try:
        account = trade_service.create_account(req.account_name)
        return AccountManageResponse(
            success=True,
            message="账户创建成功",
            account=AccountManageModel(**account),
        )
    except ValidationError as exc:
        raise_validation_http_error("创建账户校验失败 detail=%s", exc)
    except Exception as exc:
        raise_internal_http_error("创建账户失败", "创建账户失败", exc)


@router.put("/{account_id}", response_model=AccountManageResponse)
async def update_account(account_id: int, req: AccountManageRequest):
    """编辑账户名称"""
    try:
        account = trade_service.update_account_name(account_id, req.account_name)
        return AccountManageResponse(
            success=True,
            message="账户更新成功",
            account=AccountManageModel(**account),
        )
    except ValidationError as exc:
        raise_validation_http_error(
            "编辑账户校验失败 account_id=%s detail=%s",
            exc,
            account_id,
            detail_to_status=resolve_account_validation_status,
        )
    except Exception as exc:
        raise_internal_http_error("编辑账户失败 account_id=%s", "编辑账户失败", exc, account_id)


@router.delete("/{account_id}", response_model=AccountDeleteResponse)
async def delete_account(account_id: int):
    """删除账户"""
    try:
        result = trade_service.delete_account(account_id)
        return AccountDeleteResponse(
            success=True,
            message="账户删除成功",
            **result,
        )
    except ValidationError as exc:
        raise_validation_http_error(
            "删除账户校验失败 account_id=%s detail=%s",
            exc,
            account_id,
            detail_to_status=resolve_account_validation_status,
        )
    except Exception as exc:
        raise_internal_http_error("删除账户失败 account_id=%s", "删除账户失败", exc, account_id)


@router.post("/deposit", response_model=OperationResponse)
async def deposit(req: DepositRequest, account_id: int = Query(1, description="账户ID")):
    """
    入金
    """
    try:
        trade_service.deposit(account_id, req.amount, req.remark)
        return OperationResponse(
            success=True,
            message=f"入金成功: {req.amount:.2f} 元"
        )
    except ValidationError as exc:
        raise_validation_http_error("入金参数校验失败 account_id=%s detail=%s", exc, account_id)
    except Exception as exc:
        raise_internal_http_error("入金失败 account_id=%s amount=%s", "入金失败", exc, account_id, req.amount)


@router.post("/withdraw", response_model=OperationResponse)
async def withdraw(req: WithdrawRequest, account_id: int = Query(1, description="账户ID")):
    """
    出金
    """
    try:
        trade_service.withdraw(account_id, req.amount, req.remark)
        return OperationResponse(
            success=True,
            message=f"出金成功: {req.amount:.2f} 元"
        )
    except ValidationError as exc:
        raise_validation_http_error("出金参数校验失败 account_id=%s detail=%s", exc, account_id)
    except Exception as exc:
        raise_internal_http_error("出金失败 account_id=%s amount=%s", "出金失败", exc, account_id, req.amount)


@router.post("/adjust", response_model=OperationResponse)
async def adjust(req: AdjustRequest, account_id: int = Query(1, description="账户ID")):
    """
    调账
    """
    try:
        cash_flow_service.adjust(
            account_id=account_id,
            amount=req.amount,
            direction=req.direction,
            remark=req.remark,
            biz_date=req.biz_date,
        )
        return OperationResponse(
            success=True,
            message=f"调账成功: {req.direction} {req.amount:.2f} 元"
        )
    except ValidationError as exc:
        raise_validation_http_error("调账参数校验失败 account_id=%s detail=%s", exc, account_id)
    except Exception as exc:
        raise_internal_http_error("调账失败 account_id=%s amount=%s", "调账失败", exc, account_id, req.amount)


@router.get("/cash-flows", response_model=List[CashFlowResponse])
async def get_cash_flows(
    account_id: int = Query(1, description="账户ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    flow_type: Optional[str] = Query(None, description="资金流水类型"),
    limit: int = Query(100, ge=1, le=500, description="返回数量上限"),
):
    """
    查询资金流水
    """
    try:
        cash_flows = cash_flow_service.list_cash_flows(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            flow_type=flow_type,
            limit=limit,
        )
        return [CashFlowResponse(**item) for item in cash_flows]
    except ValidationError as exc:
        raise_validation_http_error("资金流水查询参数校验失败 account_id=%s detail=%s", exc, account_id)
    except Exception as exc:
        raise_internal_http_error("资金流水查询失败 account_id=%s", "资金流水查询失败", exc, account_id)


@router.post("/cash-flows", response_model=CashFlowResponse)
async def create_cash_flow(
    req: CashFlowCreateRequest,
    account_id: int = Query(1, description="账户ID"),
):
    """
    新增资金流水
    """
    try:
        cash_flow = cash_flow_service.create_cash_flow(
            account_id=account_id,
            flow_type=req.flow_type,
            amount=req.amount,
            remark=req.remark,
            biz_date=req.biz_date,
            source_type="CORPORATE_ACTION" if req.related_action_id else "MANUAL",
            source_ref_id=str(req.related_action_id) if req.related_action_id else None,
            adjust_direction=req.adjust_direction,
        )
        return CashFlowResponse(**cash_flow.to_dict())
    except ValidationError as exc:
        raise_validation_http_error("资金流水新增参数校验失败 account_id=%s detail=%s", exc, account_id)
    except Exception as exc:
        raise_internal_http_error(
            "资金流水新增失败 account_id=%s flow_type=%s",
            "资金流水新增失败",
            exc,
            account_id,
            req.flow_type,
        )


@router.post("/rebuild", response_model=RebuildResponse)
async def rebuild_account(
    account_id: int = Query(1, description="账户ID"),
    as_of_date: Optional[str] = Query(None, description="估值日期 YYYY-MM-DD，按该日及之前最近有效收盘价估值"),
):
    """
    手工触发当前账户状态重算
    """
    try:
        summary = account_rebuild_service.rebuild_current_state(account_id=account_id, as_of_date=as_of_date)
        return RebuildResponse(
            success=True,
            message="当前账户状态重算成功",
            summary=summary,
        )
    except ValidationError as exc:
        raise_validation_http_error("账户重算校验失败 account_id=%s detail=%s", exc, account_id)
    except Exception as exc:
        raise_internal_http_error("账户重算失败 account_id=%s", "账户重算失败", exc, account_id)


@router.post("/rebuild/history", response_model=RebuildResponse)
async def rebuild_account_history(
    account_id: int = Query(1, description="账户ID"),
    from_date: Optional[str] = Query(None, description="可选起始日期 YYYY-MM-DD"),
):
    """
    手工触发账户历史收益重算
    """
    try:
        summary = account_history_rebuild_service.rebuild_history(
            account_id=account_id,
            from_date=from_date,
        )
        return RebuildResponse(
            success=True,
            message=summary.get("message", "账户历史重算完成"),
            summary=summary,
        )
    except ValidationError as exc:
        raise_validation_http_error("账户历史重算校验失败 account_id=%s detail=%s", exc, account_id)
    except Exception as exc:
        raise_internal_http_error("账户历史重算失败 account_id=%s", "账户历史重算失败", exc, account_id)


@router.post("/import-rebuild", response_model=ImportRebuildResponse)
async def import_and_rebuild_account(
    req: ImportRebuildRequest,
    admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    """
    清空指定账户业务数据，导入历史文件，并重建当前状态与历史收益。
    """
    try:
        ensure_import_rebuild_access(admin_token)
        overrides, dry_run = extract_import_rebuild_payload(req)

        if dry_run:
            result = account_import_rebuild_service.preview_from_imports(overrides=overrides)
        else:
            result = account_import_rebuild_service.rebuild_from_imports(overrides=overrides)
        return build_import_rebuild_response(result, dry_run=dry_run)
    except FileNotFoundError as exc:
        raise_validation_http_error("账户导入重建文件缺失 detail=%s", exc)
    except ValidationError as exc:
        raise_validation_http_error("账户导入重建校验失败 detail=%s", exc)
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_http_error("账户导入重建失败", "账户导入重建失败", exc)
