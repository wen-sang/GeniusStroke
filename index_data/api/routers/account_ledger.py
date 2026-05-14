from fastapi import APIRouter, Query

from api.models import PaginatedResponse
from core.corporate_action import corporate_action_service

router = APIRouter(prefix="/api/account-ledger", tags=["account_ledger"])


@router.get("", response_model=PaginatedResponse)
async def get_account_ledger(
    account_id: int = Query(1, description="账户ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量"),
):
    return corporate_action_service.get_account_ledger(
        account_id=account_id,
        page=page,
        page_size=page_size,
    )
