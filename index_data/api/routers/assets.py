# 文件: api/routers/assets.py
from fastapi import APIRouter, Query
from api.error_helpers import raise_client_http_error, raise_internal_http_error
from api.schemas import AssetCreate, AssetUpdate
from api.services.asset_service import asset_service
from api.models import PaginatedResponse

router = APIRouter(
    prefix="/api/v1/assets",
    tags=["基础档案管理"]
)

@router.get("/list", response_model=PaginatedResponse)
async def get_asset_list(
    category: str = "others",
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量")
):
    """拉取特定 Tab 的档案列表"""
    try:
        return asset_service.get_assets(category, page, page_size)
    except Exception:
        raise_internal_http_error("获取资产列表失败 category=%s", "服务内部错误", category)

@router.post("")
async def create_asset_record(asset: AssetCreate):
    """新增基础档案记录并做路由联动配置"""
    try:
        return asset_service.create_asset(asset)
    except ValueError as exc:
        raise_client_http_error(
            "新增资产参数校验失败 asset_code=%s detail=%s",
            str(exc),
            asset.asset_code,
            str(exc),
        )
    except Exception:
        raise_internal_http_error("新增资产失败 asset_code=%s", "服务内部错误", asset.asset_code)

@router.put("/{asset_code}")
async def update_asset_record(asset_code: str, asset: AssetUpdate):
    """更新档案（屏蔽对主键变更的修改请求）"""
    try:
        return asset_service.update_asset(asset_code, asset)
    except ValueError as exc:
        raise_client_http_error(
            "更新资产参数校验失败 asset_code=%s detail=%s",
            str(exc),
            asset_code,
            str(exc),
        )
    except Exception:
        raise_internal_http_error("更新资产失败 asset_code=%s", "服务内部错误", asset_code)

@router.delete("/{asset_code}")
async def delete_asset_record(asset_code: str):
    """根据无关联拦截政策安全物理删除配置与路由"""
    try:
        return asset_service.delete_asset(asset_code)
    except ValueError as exc:
        raise_client_http_error(
            "删除资产参数校验失败 asset_code=%s detail=%s",
            str(exc),
            asset_code,
            str(exc),
        )
    except Exception:
        raise_internal_http_error("删除资产失败 asset_code=%s", "服务内部错误", asset_code)
