# 文件: dao/fund_daily_dao.py
from typing import List, Dict, Optional
from config.constants import DataSource
from core.db_engine import db_engine
from utils.logger import logger


class FundDailyDAO:
    """
    基金日线数据 DAO (dat_fund_daily)
    管理净值数据的增删改查
    """

    def upsert_batch(self, data_list: List[Dict]) -> int:
        """
        批量 upsert 净值数据
        
        :param data_list: [{'asset_code': '159516', 'trade_date': '2026-01-29', 
                            'unit_nav': 0.7386, 'accum_nav': 1.8398, 'source_id': 'lixinren'}, ...]
        :return: 插入/更新的行数
        """
        if not data_list:
            return 0

        sql = """
        INSERT INTO dat_fund_daily (asset_code, trade_date, unit_nav, accum_nav, source_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(asset_code, trade_date) 
        DO UPDATE SET
            unit_nav = excluded.unit_nav,
            accum_nav = excluded.accum_nav,
            source_id = excluded.source_id,
            updated_at = datetime('now', 'localtime')
        """

        rows = []
        for item in data_list:
            source_id = DataSource.validate_asset_route(
                item.get('source_id', DataSource.LIXINREN)
            )
            rows.append((
                item['asset_code'],
                item['trade_date'],
                item.get('unit_nav'),
                item.get('accum_nav'),
                source_id
            ))

        try:
            with db_engine.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(sql, rows)
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Upsert fund daily data failed: {e}")
            raise e

    def get_last_date(self, asset_code: str) -> Optional[str]:
        """
        获取指定资产的最新净值数据日期
        
        :param asset_code: 资产代码
        :return: 最新日期 (YYYY-MM-DD) 或 None
        """
        sql = """
        SELECT MAX(trade_date) 
        FROM dat_fund_daily 
        WHERE asset_code = ?
        """

        try:
            with db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (asset_code,))
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"Get last fund daily date failed ({asset_code}): {e}")
            return None

    def get_last_dates_batch(self, asset_codes: List[str]) -> Dict[str, Optional[str]]:
        """
        批量获取多个资产的最新净值数据日期 (性能优化)
        
        :param asset_codes: 资产代码列表
        :return: {asset_code: last_date, ...}
        """
        if not asset_codes:
            return {}

        placeholders = ','.join(['?'] * len(asset_codes))
        sql = f"""
        SELECT asset_code, MAX(trade_date) as last_date
        FROM dat_fund_daily
        WHERE asset_code IN ({placeholders})
        GROUP BY asset_code
        """

        result_map = {code: None for code in asset_codes}

        try:
            with db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, asset_codes)
                rows = cursor.fetchall()
                
                for code, last_date in rows:
                    result_map[code] = last_date
                
                return result_map
        except Exception as e:
            logger.error(f"Batch get last fund daily dates failed: {e}")
            return result_map

    def get_data(self, asset_code: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        查询净值数据
        
        :param asset_code: 资产代码
        :param start_date: 起始日期 (可选)
        :param end_date: 结束日期 (可选)
        :return: 数据列表
        """
        sql = "SELECT trade_date, unit_nav, accum_nav FROM dat_fund_daily WHERE asset_code = ?"
        params = [asset_code]

        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        
        sql += " ORDER BY trade_date ASC"

        try:
            with db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                
                return [
                    {
                        'trade_date': row[0],
                        'unit_nav': row[1],
                        'accum_nav': row[2]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Get fund daily data failed ({asset_code}): {e}")
            return []


# 单例
fund_daily_dao = FundDailyDAO()
