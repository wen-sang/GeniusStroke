from typing import List, Optional
from dao.base_dao import BaseDAO
from utils.types import AssetMeta, RouterRule, DataSourceConfig
from utils.logger import logger


class MetaDAO(BaseDAO):
    """负责读取配置表 (sys_asset_meta, sys_datasource, sys_data_router)"""
    
    @property
    def table_name(self) -> str:
        return 'sys_asset_meta'
    
    def get_active_assets(self) -> List[AssetMeta]:
        """获取所有在市的标的"""
        sql = """
        SELECT
            asset_code,
            asset_name,
            asset_type,
            exchange,
            listing_date,
            is_active,
            market_category,
            tags,
            is_watchlist
        FROM sys_asset_meta
        WHERE is_active = 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)  # 使用基类方法
    
    def get_datasource_config(self, source_id: str) -> Optional[DataSourceConfig]:
        """获取指定数据源的配置 (Token等)"""
        sql = """
        SELECT
            source_id,
            api_token,
            is_enable,
            priority,
            extra_config
        FROM sys_datasource
        WHERE source_id = ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (source_id,))
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)  # 使用基类方法
    
    def get_router_rules(self) -> List[RouterRule]:
        """获取所有路由规则，按优先级排序 (数值越小越优先)"""
        sql = """
        SELECT
            id,
            asset_code,
            asset_type,
            interface,
            source_id,
            source_code,
            priority
        FROM sys_data_router
        ORDER BY priority ASC
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)  # 使用基类方法
    
    # v2.4.5 新增方法
    
    def get_asset_meta(self, asset_code: str) -> Optional[dict]:
        """获取单个资产元数据"""
        sql = """
        SELECT
            asset_code,
            asset_name,
            asset_type,
            exchange,
            listing_date,
            is_active,
            market_category,
            tags,
            is_watchlist
        FROM sys_asset_meta
        WHERE asset_code = ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code,))
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)
    
    def upsert_asset_meta(self, asset_code: str, asset_name: str,
                          asset_type: str = 'ETF', 
                          market_category: str = 'EXCHANGE',
                          exchange: str = None,
                          listing_date: str = None,
                          is_active: int = 1) -> None:
        """创建或更新资产元数据"""
        sql = """
        INSERT INTO sys_asset_meta (asset_code, asset_name, asset_type, 
                                    market_category, exchange, listing_date, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_code) DO UPDATE SET
            asset_name = excluded.asset_name,
            asset_type = excluded.asset_type,
            market_category = excluded.market_category,
            exchange = COALESCE(excluded.exchange, sys_asset_meta.exchange),
            listing_date = COALESCE(excluded.listing_date, sys_asset_meta.listing_date),
            is_active = excluded.is_active
        """
        with self.db_engine.get_connection() as conn:
            conn.execute(sql, (asset_code, asset_name, asset_type, 
                               market_category, exchange, listing_date, is_active))

    def get_quote_route_meta_batch(self, asset_codes: List[str]) -> dict:
        """批量获取行情的路由元数据（按标的和类型规则，选出最高优先级）。"""
        if not asset_codes:
            return {}
        
        placeholders = ",".join(["?"] * len(asset_codes))
        sql = f"""
        SELECT
            m.asset_code,
            m.asset_type,
            m.exchange,
            r.source_code,
            r.source_id AS route_source_id,
            r.priority,
            CASE WHEN r.asset_code IS NOT NULL THEN 0 ELSE 1 END AS route_rank
        FROM sys_asset_meta m
        LEFT JOIN sys_data_router r
          ON r.interface = 'daily_bar'
         AND (
              r.asset_code = m.asset_code
              OR (r.asset_code IS NULL AND r.asset_type = m.asset_type)
         )
        WHERE m.asset_code IN ({placeholders})
        ORDER BY m.asset_code, route_rank ASC, r.priority ASC
        """
        
        result = {}
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, asset_codes)
            columns = [column[0] for column in cursor.description]
            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))
                code = row_dict["asset_code"]
                if code not in result:
                    result[code] = row_dict
        return result


meta_dao = MetaDAO()
