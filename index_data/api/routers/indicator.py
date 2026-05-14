# 文件: api/routers/indicator.py
from fastapi import APIRouter, Query
from api.models import PaginatedResponse
from api.services.indicator_service import IndicatorService

router = APIRouter(prefix="/api", tags=["indicator"])


@router.get("/indicator", response_model=PaginatedResponse)
async def get_indicator_data(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量")
):
    """
    获取技术指标数据
    
    - **page**: 页码（默认1）
    - **page_size**: 每页数量（默认60，最大100）
    """
    service = IndicatorService()
    result = service.get_indicator_data(page=page, page_size=page_size)
    return result
