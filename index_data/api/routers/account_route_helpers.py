from typing import Any, Callable, NoReturn, Optional

from fastapi import HTTPException

from api.error_helpers import raise_internal_http_error as raise_api_internal_http_error
from config import settings
from utils.logger import logger
from utils.validators import ValidationError

from api.routers.account_models import AccountSummaryResponse, ImportRebuildRequest, ImportRebuildResponse


def ensure_import_rebuild_access(admin_token: Optional[str]) -> None:
    if not settings.ENABLE_IMPORT_REBUILD_API:
        raise HTTPException(status_code=403, detail="当前环境未启用导入重建接口")

    if settings.MANAGEMENT_API_TOKEN:
        if admin_token != settings.MANAGEMENT_API_TOKEN:
            raise HTTPException(status_code=403, detail="管理令牌无效")
        return

    if settings.ENV != "development":
        raise HTTPException(status_code=403, detail="非开发环境必须配置管理令牌")


def build_account_summary_response(summary: Any) -> AccountSummaryResponse:
    return AccountSummaryResponse(
        account_id=summary.account_id,
        account_name=summary.account_name,
        broker_name=summary.broker_name,
        cash_balance=summary.cash_balance,
        total_market_value=summary.total_market_value,
        total_asset=summary.total_asset,
        total_deposit=summary.total_deposit,
        total_withdraw=summary.total_withdraw,
        acc_profit=summary.acc_profit,
        floating_pnl=summary.floating_pnl,
        daily_return=summary.daily_return,
        daily_return_rate=summary.daily_return_rate,
        history_total_pnl=summary.history_total_pnl,
        history_total_pnl_rate=summary.history_total_pnl_rate,
        account_xirr=summary.account_xirr,
        data_updated_to=summary.data_updated_to,
        commission_rate=summary.commission_rate,
        commission_min=summary.commission_min,
        stamp_duty_rate=summary.stamp_duty_rate,
    )


def extract_import_rebuild_payload(req: ImportRebuildRequest) -> tuple[dict[str, Any], bool]:
    overrides = req.model_dump(exclude_none=True)
    if "cash_reconcile" in overrides and overrides["cash_reconcile"] is None:
        overrides.pop("cash_reconcile", None)
    dry_run = bool(overrides.pop("dry_run", False))
    return overrides, dry_run


def build_import_rebuild_response(result: dict[str, Any], dry_run: bool) -> ImportRebuildResponse:
    if result.get("cancelled"):
        return ImportRebuildResponse(
            success=False,
            message="导入重建已取消",
            account_id=result.get("account_id"),
            preview=result.get("preview") or {},
        )

    return ImportRebuildResponse(
        success=bool(result.get("success")),
        message="账户导入重建预检查成功" if dry_run else "账户导入重建成功",
        account_id=result.get("account_id"),
        preview=result.get("preview") or {},
        current_summary=result.get("current_summary") or {},
        history_summary=result.get("history_summary") or {},
    )


def resolve_account_validation_status(detail: str) -> int:
    return 404 if detail == "账户不存在" else 400


def resolve_cash_flow_account_id(
    query_account_id: Optional[int],
    body_account_id: Optional[int],
    *,
    default_account_exists: bool,
    endpoint: str,
) -> int:
    if (
        query_account_id is not None
        and body_account_id is not None
        and query_account_id != body_account_id
    ):
        raise ValidationError("查询参数与请求体的账户ID不一致")
    if query_account_id is not None:
        return query_account_id
    if body_account_id is not None:
        logger.warning(
            "资金接口使用请求体账户ID兼容路径 endpoint=%s account_id=%s source=body_compat",
            endpoint,
            body_account_id,
        )
        return body_account_id
    if default_account_exists:
        return 1
    raise ValidationError("必须指定账户")


def raise_validation_http_error(
    log_message: str,
    exc: ValidationError | FileNotFoundError,
    *log_args: Any,
    status_code: int = 400,
    detail_to_status: Optional[Callable[[str], int]] = None,
) -> NoReturn:
    detail = str(exc)
    logger.warning(log_message, *log_args, detail)
    resolved_status = detail_to_status(detail) if detail_to_status else status_code
    raise HTTPException(status_code=resolved_status, detail=detail)


def raise_internal_http_error(
    log_message: str,
    detail_prefix: str,
    exc: Exception,
    *log_args: Any,
) -> NoReturn:
    _ = exc
    raise_api_internal_http_error(log_message, detail_prefix, *log_args)
