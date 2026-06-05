# 文件: dao/indicator_dao.py
from typing import List, Dict, Optional, Any
from core.db_engine import db_engine
from dao.base_dao import BaseDAO
from utils.logger import logger


class IndicatorDAO(BaseDAO):
    """技术指标数据 DAO"""
    
    @property
    def table_name(self) -> str:
        return 'dat_indicator_daily'

    def get_last_indicator_date(self, asset_code: str, config_id: int) -> Optional[str]:
        """
        获取某资产某特定指标配置在库中的最新日期
        用途: 用于计算引擎判断从哪一天开始进行增量计算
        :return: 'YYYY-MM-DD' or None
        """
        sql = "SELECT MAX(trade_date) FROM dat_indicator_daily WHERE asset_code = ? AND config_id = ?"
        
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (asset_code, config_id))
                res = cursor.fetchone()
                return res[0] if res else None
        except Exception as e:
            logger.error(f"Error getting last indicator date for {asset_code}, cfg={config_id}: {e}")
            return None

    def get_latest_trade_date_global(self) -> Optional[str]:
        """获取指标表的全局最新交易日"""
        sql = "SELECT MAX(trade_date) FROM dat_indicator_daily"
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"Error getting latest indicator trade date: {e}")
            return None

    def get_index_indicator_rows_by_date(self, trade_date: str) -> List[Dict]:
        """获取指定日期 INDEX 资产的指标原始行（用于服务层合并 JSON）"""
        sql = """
        SELECT
            i.trade_date AS trade_date,
            i.asset_code AS asset_code,
            meta.asset_name AS asset_name,
            m.close AS close_price,
            i.val_json AS val_json
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        LEFT JOIN dat_market_daily m ON i.asset_code = m.asset_code AND i.trade_date = m.trade_date
        WHERE i.trade_date = ?
          AND meta.asset_type = 'INDEX'
        ORDER BY i.asset_code
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (trade_date,))
                rows = cursor.fetchall()
                return self._rows_to_dicts(cursor, rows)
        except Exception as e:
            logger.error(f"Error loading indicator rows for date {trade_date}: {e}")
            return []

    def get_indicator_rows_by_date(
        self,
        trade_date: str,
        group: str = "index",
    ) -> List[Dict]:
        """获取指定日期、指定资产分组的指标原始行。"""
        asset_type_filter = self._asset_type_filter(group)
        sql = """
        SELECT
            i.trade_date AS trade_date,
            i.asset_code AS asset_code,
            meta.asset_name AS asset_name,
            m.close AS close_price,
            i.val_json AS val_json
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        LEFT JOIN dat_market_daily m ON i.asset_code = m.asset_code AND i.trade_date = m.trade_date
        WHERE i.trade_date = ?
          AND {asset_type_filter}
        ORDER BY i.asset_code
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql.format(asset_type_filter=asset_type_filter), (trade_date,))
                rows = cursor.fetchall()
                return self._rows_to_dicts(cursor, rows)
        except Exception as e:
            logger.error(f"Error loading indicator rows for date {trade_date}: {e}")
            return []

    def count_index_assets_by_date(self, trade_date: str) -> int:
        """统计指定日期存在指标数据的 INDEX 资产数量（按 asset_code 去重）"""
        sql = """
        SELECT COUNT(DISTINCT i.asset_code)
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        WHERE i.trade_date = ?
          AND meta.asset_type = 'INDEX'
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (trade_date,))
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            logger.error(f"Error counting indicator assets for date {trade_date}: {e}")
            return 0

    def count_assets_by_date(self, trade_date: str, group: str = "index") -> int:
        """统计指定日期存在指标数据的资产数量（按 asset_code 去重）。"""
        asset_type_filter = self._asset_type_filter(group)
        sql = """
        SELECT COUNT(DISTINCT i.asset_code)
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        WHERE i.trade_date = ?
          AND {asset_type_filter}
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql.format(asset_type_filter=asset_type_filter), (trade_date,))
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            logger.error(f"Error counting indicator assets for date {trade_date}: {e}")
            return 0

    def get_index_asset_codes_page_by_date(self, trade_date: str, limit: int, offset: int) -> List[str]:
        """分页获取指定日期 INDEX 资产代码列表（稳定排序：asset_code 升序）"""
        sql = """
        SELECT DISTINCT i.asset_code
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        WHERE i.trade_date = ?
          AND meta.asset_type = 'INDEX'
        ORDER BY i.asset_code
        LIMIT ? OFFSET ?
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (trade_date, limit, offset))
                return [row[0] for row in cursor.fetchall() if row and row[0]]
        except Exception as e:
            logger.error(f"Error loading indicator asset code page for date {trade_date}: {e}")
            return []

    def get_asset_codes_page_by_date(
        self,
        trade_date: str,
        group: str = "index",
        limit: int = 60,
        offset: int = 0,
    ) -> List[str]:
        """分页获取指定日期、指定资产分组的资产代码列表。"""
        asset_type_filter = self._asset_type_filter(group)
        sql = """
        SELECT DISTINCT i.asset_code
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        WHERE i.trade_date = ?
          AND {asset_type_filter}
        ORDER BY i.asset_code
        LIMIT ? OFFSET ?
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    sql.format(asset_type_filter=asset_type_filter),
                    (trade_date, limit, offset),
                )
                return [row[0] for row in cursor.fetchall() if row and row[0]]
        except Exception as e:
            logger.error(f"Error loading indicator asset code page for date {trade_date}: {e}")
            return []

    def get_index_indicator_rows_by_date_and_codes(self, trade_date: str, asset_codes: List[str]) -> List[Dict]:
        """获取指定日期 + 代码集合的指标原始行（用于服务层合并 JSON）"""
        if not asset_codes:
            return []
        placeholders = ",".join(["?"] * len(asset_codes))
        sql = f"""
        SELECT
            i.trade_date AS trade_date,
            i.asset_code AS asset_code,
            meta.asset_name AS asset_name,
            m.close AS close_price,
            i.val_json AS val_json
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        LEFT JOIN dat_market_daily m ON i.asset_code = m.asset_code AND i.trade_date = m.trade_date
        WHERE i.trade_date = ?
          AND meta.asset_type = 'INDEX'
          AND i.asset_code IN ({placeholders})
        ORDER BY i.asset_code
        """
        params = [trade_date] + list(asset_codes)
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return self._rows_to_dicts(cursor, rows)
        except Exception as e:
            logger.error(f"Error loading indicator rows for date {trade_date} with paged codes: {e}")
            return []

    def get_indicator_rows_by_date_and_codes(
        self,
        trade_date: str,
        group: str,
        asset_codes: List[str],
    ) -> List[Dict]:
        """获取指定日期、资产分组和代码集合的指标原始行。"""
        if not asset_codes:
            return []
        placeholders = ",".join(["?"] * len(asset_codes))
        asset_type_filter = self._asset_type_filter(group)
        sql = f"""
        SELECT
            i.trade_date AS trade_date,
            i.asset_code AS asset_code,
            meta.asset_name AS asset_name,
            m.close AS close_price,
            i.val_json AS val_json
        FROM dat_indicator_daily i
        JOIN sys_asset_meta meta ON i.asset_code = meta.asset_code
        LEFT JOIN dat_market_daily m ON i.asset_code = m.asset_code AND i.trade_date = m.trade_date
        WHERE i.trade_date = ?
          AND {asset_type_filter}
          AND i.asset_code IN ({placeholders})
        ORDER BY i.asset_code
        """
        params = [trade_date] + list(asset_codes)
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return self._rows_to_dicts(cursor, rows)
        except Exception as e:
            logger.error(f"Error loading indicator rows for date {trade_date} with paged codes: {e}")
            return []

    @staticmethod
    def _asset_type_filter(group: str) -> str:
        if group == "non_index":
            return "meta.asset_type != 'INDEX'"
        if group == "index":
            return "meta.asset_type = 'INDEX'"
        raise ValueError(f"Unsupported indicator group: {group}")

    def upsert_batch(self, data_list: List[Dict]):
        """
        批量写入指标数据 (Upsert 模式)
        
        :param data_list: 列表，每个元素为字典:
            {
                'asset_code': '000001',
                'trade_date': '2023-12-01',
                'config_id': 101,
                'val_json': '{"SMA_5": 10.2}' (注意: 这里必须是 JSON 字符串，不是对象)
            }
        """
        if not data_list:
            return

        # 使用 ON CONFLICT DO UPDATE 实现幂等写入
        sql = """
        INSERT INTO dat_indicator_daily (asset_code, trade_date, config_id, val_json)
        VALUES (:asset_code, :trade_date, :config_id, :val_json)
        ON CONFLICT(asset_code, trade_date, config_id) 
        DO UPDATE SET 
            val_json=excluded.val_json,
            created_at=datetime('now', 'localtime')
        """
        
        try:
            with self.db_engine.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(sql, data_list)
                # 上下文管理器会自动 commit
        except Exception as e:
            # 这里记录个大概，具体的堆栈由调用方(Engine)记录到 calc.log
            logger.error(f"Batch Upsert Indicator Failed (Count: {len(data_list)}): {e}")
            raise e

    def delete_asset_from_date(self, asset_code: str, from_date: str) -> int:
        sql = """
        DELETE FROM dat_indicator_daily
        WHERE asset_code = ?
          AND trade_date >= ?
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code, from_date))
            return cursor.rowcount

# 单例导出
indicator_dao = IndicatorDAO()
