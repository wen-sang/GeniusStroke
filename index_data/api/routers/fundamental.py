# 文件: api/routers/fundamental.py
from fastapi import APIRouter, Query
from api.models import PaginatedResponse
from api.services.fundamental_service import FundamentalService

router = APIRouter(prefix="/api", tags=["fundamental"])


@router.get("/fundamental", response_model=PaginatedResponse)
async def get_fundamental_data(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量")
):
    """
    获取基本面数据
    
    - **page**: 页码（默认1）
    - **page_size**: 每页数量（默认60，最大100）
    """
    service = FundamentalService()
    result = service.get_fundamental_data(page=page, page_size=page_size)
    return result
