# 文件: api/routers/indicator.py
from fastapi import APIRouter, HTTPException, Query
from api.error_helpers import raise_internal_http_error
from api.models import PaginatedResponse
from api.services.indicator_service import IndicatorService

router = APIRouter(prefix="/api", tags=["indicator"])


@router.get("/indicator", response_model=PaginatedResponse)
async def get_indicator_data(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量"),
    group: str = "index",
):
    """
    获取技术指标数据
    
    - **page**: 页码（默认1）
    - **page_size**: 每页数量（默认60，最大100）
    - **group**: 资产分组（默认 index，保持旧接口行为）
    """
    if group not in {"index", "non_index"}:
        raise HTTPException(status_code=422, detail="group must be index or non_index")

    service = IndicatorService()
    try:
        return service.get_indicator_data(page=page, page_size=page_size, group=group)
    except Exception:
        raise_internal_http_error(
            "技术指标查询失败 page=%s page_size=%s group=%s",
            "技术指标查询失败",
            page,
            page_size,
            group,
        )
