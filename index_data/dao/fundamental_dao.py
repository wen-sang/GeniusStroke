# dao/fundamental_dao.py
from typing import List, Dict, Optional, Any
from config.constants import DataSource
from dao.base_dao import BaseDAO
from utils.logger import logger


class FundamentalDAO(BaseDAO):
    """基本面数据 DAO"""
    
    @property
    def table_name(self) -> str:
        return 'dat_fundamental_daily'

    def get_last_update_date(self, asset_code: str) -> Optional[str]:
        """
        获取指定标的在数据库中的最新日期
        用于 Init Mode 判断起点
        """
        sql = ("SELECT MAX(trade_date) FROM dat_fundamental_daily "
               "WHERE asset_code = ?")
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (asset_code,))
                res = cursor.fetchone()
                return res[0] if res else None
        except Exception as e:
            logger.error(f"DAO Error (get_last_update_date): {e}")
            return None

    def get_latest_trade_date_global(self) -> Optional[str]:
        """获取基本面表的全局最新交易日"""
        sql = "SELECT MAX(trade_date) FROM dat_fundamental_daily"
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"DAO Error (get_latest_trade_date_global): {e}")
            return None

    def get_index_fundamental_count_by_date(self, trade_date: str) -> int:
        """获取指定交易日的 INDEX 基本面总数"""
        sql = """
        SELECT COUNT(*)
        FROM dat_fundamental_daily f
        JOIN sys_asset_meta meta ON f.asset_code = meta.asset_code
        WHERE f.trade_date = ?
          AND meta.asset_type = 'INDEX'
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (trade_date,))
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"DAO Error (get_index_fundamental_count_by_date): {e}")
            return 0

    def get_index_fundamental_page_by_date(self, trade_date: str, limit: int, offset: int) -> List[Dict]:
        """获取指定交易日的 INDEX 基本面分页数据"""
        sql = """
        SELECT
            f.trade_date AS trade_date,
            f.asset_code AS asset_code,
            meta.asset_name AS asset_name,
            f.pe_ttm AS pe_ttm,
            f.pb AS pb,
            f.pe_pos_5y AS pe_pos_5y,
            f.full_stats_json AS full_stats_json
        FROM dat_fundamental_daily f
        JOIN sys_asset_meta meta ON f.asset_code = meta.asset_code
        WHERE f.trade_date = ?
          AND meta.asset_type = 'INDEX'
        ORDER BY f.asset_code
        LIMIT ? OFFSET ?
        """
        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (trade_date, limit, offset))
                rows = cursor.fetchall()
                return self._rows_to_dicts(cursor, rows)
        except Exception as e:
            logger.error(f"DAO Error (get_index_fundamental_page_by_date): {e}")
            return []

    def get_last_update_dates_batch(self, asset_codes: List[str]) -> Dict[str, Optional[str]]:
        """
        批量获取多个资产的最新基本面数据日期

        性能优化：将 N 次数据库查询合并为 1 次
        
        :param asset_codes: 资产代码列表
        :return: {asset_code: last_date} 字典
        """
        if not asset_codes:
            return {}

        placeholders = ','.join('?' * len(asset_codes))
        sql = f"""
        SELECT asset_code, MAX(trade_date) as last_date
        FROM dat_fundamental_daily
        WHERE asset_code IN ({placeholders})
        GROUP BY asset_code
        """

        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, asset_codes)
                result_dict = {row[0]: row[1] for row in cursor.fetchall()}

            # 补充未查询到的资产
            for code in asset_codes:
                if code not in result_dict:
                    result_dict[code] = None

            return result_dict
        except Exception as e:
            logger.error(f"DAO Error (get_last_update_dates_batch): {e}")
            return {}

    def upsert_batch(self, data_list: List[Dict]):
        """
        批量写入/更新基本面数据
        :param data_list: 清洗后的字典列表，Keys 必须与数据库列名一致
        """
        if not data_list:
            return

        # 构造 SQL 语句 (列名较多，显式列出以防顺序错误)
        # 必须包含所有在 METRICS_MAPPING 中的 key + full_stats_json + asset_code + trade_date + source_id
        cols = [
            "asset_code", "trade_date", "source_id",
            "pe_ttm", "pb", "ps_ttm", "dyr",
            "pe_pos_fs", "pe_pos_10y", "pe_pos_5y", "pe_pos_3y",
            "pb_pos_fs", "pb_pos_10y", "pb_pos_5y", "pb_pos_3y",
            "ps_pos_fs", "ps_pos_10y", "ps_pos_5y", "ps_pos_3y",
            "dyr_pos_fs", "dyr_pos_10y", "dyr_pos_5y", "dyr_pos_3y",
            "full_stats_json"
        ]
        
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        
        # 构造 UPDATE SET 子句 (排除主键)
        update_set = []
        for c in cols:
            if c not in ["asset_code", "trade_date"]:
                update_set.append(f"{c}=excluded.{c}")
        update_str = ",".join(update_set)

        sql = f"""
        INSERT INTO dat_fundamental_daily ({col_str}, updated_at)
        VALUES ({placeholders}, datetime('now', 'localtime'))
        ON CONFLICT(asset_code, trade_date) 
        DO UPDATE SET {update_str}, updated_at=datetime('now', 'localtime')
        """

        # 转换为 tuple list，确保顺序
        batch_args = []
        for row in data_list:
            source_id = DataSource.validate_asset_route(row.get('source_id'))
            # 使用 .get() 防止部分字段缺失导致 KeyError (设为 None)
            arg = tuple(
                source_id if c == 'source_id' else row.get(c)
                for c in cols
            )
            batch_args.append(arg)

        try:
            with self.db_engine.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(sql, batch_args)
                # logger.debug(f"DAO Upsert Success: {len(data_list)} rows")
        except Exception as e:
            logger.error(f"DAO Error (upsert_batch): {e}")
            raise e

# 单例导出
fundamental_dao = FundamentalDAO()
