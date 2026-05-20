from fastapi import APIRouter, HTTPException, Query

from api.error_helpers import raise_internal_http_error
from api.services.asset_catalog_service import asset_catalog_service


router = APIRouter(
    prefix="/api/v1/catalog",
    tags=["标的目录搜索"],
)


@router.get("/search")
async def search_unified_catalog(
    keyword: str = Query(..., description="代码、外部代码或名称关键字"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
):
    normalized_keyword = keyword.strip()
    if not normalized_keyword:
        raise HTTPException(status_code=422, detail="keyword 不能为空")
    try:
        return asset_catalog_service.search_unified_catalog(
            keyword=normalized_keyword,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        raise_internal_http_error("统一目录搜索失败 keyword=%s", "服务内部错误", normalized_keyword)
