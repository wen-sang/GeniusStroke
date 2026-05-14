# 文件: api/services/asset_service.py
from core.router import router
from api.schemas import AssetCreate, AssetUpdate
from typing import Dict, Any
from config.constants import DataSource
from dao.asset_dao import asset_dao
from utils.logger import logger


class AssetService:
    @staticmethod
    def _validate_source_id(source_id: str) -> str:
        """校验资产路由数据源，避免非法来源写入路由表。"""
        return DataSource.validate_asset_route(source_id)

    @staticmethod
    def _refresh_router_cache(action: str, asset_code: str) -> None:
        """写事务提交后刷新运行时路由缓存。"""
        try:
            router.reload_rules()
        except Exception:
            logger.exception("资产%s后刷新路由缓存失败 asset_code=%s", action, asset_code)

    def get_assets(self, category: str = "others", page: int = 1, page_size: int = 60) -> Dict[str, Any]:
        """
        根据 category 获取档案列表 (左连查询路由表)
        """
        return asset_dao.list_assets(category, page, page_size)

    def create_asset(self, asset: AssetCreate) -> Dict[str, Any]:
        """
        新增档案 (带事务联动)
        """
        source_id = self._validate_source_id(asset.source_id)
        asset_dao.create_asset(
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            exchange=asset.exchange,
            listing_date=asset.listing_date,
            market_category=asset.market_category,
            source_id=source_id,
        )
        self._refresh_router_cache("新增", asset.asset_code)
        return {"status": "success", "asset_code": asset.asset_code}

    def update_asset(self, asset_code: str, asset: AssetUpdate) -> Dict[str, Any]:
        """
        修改档案 (主键防爆破)
        """
        source_id = self._validate_source_id(asset.source_id)
        asset_dao.update_asset(
            asset_code=asset_code,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            exchange=asset.exchange,
            listing_date=asset.listing_date,
            market_category=asset.market_category,
            source_id=source_id,
        )
        self._refresh_router_cache("更新", asset_code)
        return {"status": "success"}

    def delete_asset(self, asset_code: str) -> Dict[str, Any]:
        """
        安全物理删除
        """
        result = asset_dao.delete_asset(asset_code)
        self._refresh_router_cache("删除", asset_code)
        return result

asset_service = AssetService()
