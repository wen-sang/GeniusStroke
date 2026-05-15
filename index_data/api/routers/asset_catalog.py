from fastapi import APIRouter, Query

from api.error_helpers import raise_client_http_error, raise_internal_http_error
from api.services.asset_catalog_service import asset_catalog_service


router = APIRouter(
    prefix="/api/v1/asset-catalog",
    tags=["外部标的目录"],
)


@router.get("/sources")
async def list_asset_catalog_sources():
    try:
        return asset_catalog_service.list_sources()
    except Exception:
        raise_internal_http_error("查询目录来源失败", "服务内部错误")


@router.get("/search")
async def search_asset_catalog(
    source_id: str = Query(..., description="目录来源"),
    keyword: str | None = Query(None, description="代码、外部代码或名称关键字"),
    asset_type: str | None = Query(None, description="资产类型"),
    exchange: str | None = Query(None, description="交易所"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    try:
        return asset_catalog_service.search_catalog(
            source_id=source_id,
            keyword=keyword,
            asset_type=asset_type,
            exchange=exchange,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise_client_http_error(
            "查询目录参数校验失败 source_id=%s detail=%s",
            str(exc),
            source_id,
            str(exc),
        )
    except Exception:
        raise_internal_http_error("查询目录失败 source_id=%s", "服务内部错误", source_id)


@router.post("/sync")
async def sync_asset_catalog(payload: dict):
    source_id = payload.get("source_id")
    try:
        if not source_id:
            raise ValueError("source_id 不能为空")
        return asset_catalog_service.sync_source(source_id=source_id, force=True)
    except ValueError as exc:
        raise_client_http_error(
            "目录同步参数校验失败 source_id=%s detail=%s",
            str(exc),
            source_id,
            str(exc),
        )
    except Exception:
        raise_internal_http_error("目录同步失败 source_id=%s", "服务内部错误", source_id)


@router.get("/sync/status")
async def get_asset_catalog_sync_status(source_id: str = Query(...)):
    try:
        return asset_catalog_service.get_sync_status(source_id)
    except ValueError as exc:
        raise_client_http_error(
            "查询目录同步状态参数校验失败 source_id=%s detail=%s",
            str(exc),
            source_id,
            str(exc),
        )
    except Exception:
        raise_internal_http_error("查询目录同步状态失败 source_id=%s", "服务内部错误", source_id)


@router.get("/sync-status")
async def get_asset_catalog_sync_status_legacy(source_id: str = Query(...)):
    return await get_asset_catalog_sync_status(source_id)
