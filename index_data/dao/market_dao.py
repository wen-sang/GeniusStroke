import pandas as pd
from typing import Dict, List, Optional, Tuple
from config.constants import DataSource
from dao.base_dao import BaseDAO
from utils.validators import ValidationError


class MarketDAO(BaseDAO):
    """市场行情数据 DAO"""
    
    @property
    def table_name(self) -> str:
        return 'dat_market_daily'

    def _fetch_latest_asset_snapshots(
        self,
        table_name: str,
        table_alias: str,
        asset_codes: List[str],
        select_clause: str,
        extra_conditions: Optional[List[str]] = None,
        extra_params: tuple = (),
    ) -> List[tuple]:
        """查询指定资产在最近交易日的快照行。"""
        placeholders = self._build_placeholders(asset_codes)
        latest_subquery = self._build_latest_trade_date_subquery(
            table_name,
            placeholders,
            extra_conditions=extra_conditions,
        )
        sql = f"""
        SELECT
            {select_clause}
        FROM {table_name} {table_alias}
        LEFT JOIN sys_asset_meta a ON {table_alias}.asset_code = a.asset_code
        JOIN (
{latest_subquery}
        ) t
          ON {table_alias}.asset_code = t.asset_code
         AND {table_alias}.trade_date = t.latest_trade_date
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (*asset_codes, *extra_params))
            return cursor.fetchall()

    # --- Calendar ---
    def get_trade_calendar(self, conn=None) -> List[str]:
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT trade_date FROM trade_calendar ORDER BY trade_date ASC"
            )
            return [r[0] for r in cursor.fetchall()]

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT trade_date FROM trade_calendar ORDER BY trade_date ASC"
            )
            return [r[0] for r in cursor.fetchall()]

    def is_trade_date(self, trade_date: str) -> bool:
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM trade_calendar WHERE trade_date = ? LIMIT 1",
                (trade_date,),
            )
            return cursor.fetchone() is not None

    def update_calendar(self, date_list: List[str]):
        """全量更新交易日历"""
        if not date_list:
            return
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trade_calendar")
            cursor.executemany(
                "INSERT INTO trade_calendar VALUES (?)",
                [(d,) for d in date_list]
            )
            
    # --- Raw Layer ---
    def save_raw_log(self, batch_id, asset_code, source_id, req_params,
                     compressed_payload) -> int:
        """保存原始 API 数据，返回 row_id"""
        source_id = DataSource.validate_asset_route(source_id)
        sql = """
        INSERT INTO dat_raw_api_log (batch_id, asset_code, source_id, req_params, resp_payload, status)
        VALUES (?, ?, ?, ?, ?, 0)
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                sql,
                (batch_id, asset_code, source_id, req_params,
                 compressed_payload)
            )
            return cursor.lastrowid

    def update_raw_status(self, log_id: int, status: int):
        """更新 Raw Log 处理状态 (1=Success, -1=Fail)"""
        with self.db_engine.get_connection() as conn:
            conn.execute(
                "UPDATE dat_raw_api_log SET status = ? WHERE id = ?",
                (status, log_id)
            )

    # --- Std Layer ---
    def get_last_date(self, asset_code: str) -> Optional[str]:
        """获取本地最新数据的日期"""
        sql = "SELECT MAX(trade_date) FROM dat_market_daily WHERE asset_code = ?"
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code,))
            res = cursor.fetchone()
            return res[0] if res else None

    def get_latest_trade_date_global(self, conn=None) -> Optional[str]:
        """获取行情表的全局最新交易日"""
        sql = "SELECT MAX(trade_date) FROM dat_market_daily"
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

    def get_close_price_map(
        self,
        asset_codes: List[str],
        start_date: str,
        conn=None,
    ) -> Dict[Tuple[str, str], float]:
        """批量读取指定日期起的市场收盘价 map。"""
        if not asset_codes:
            return {}

        placeholders = self._build_placeholders(asset_codes)
        sql = f"""
        SELECT asset_code, trade_date, close
        FROM dat_market_daily
        WHERE asset_code IN ({placeholders})
          AND trade_date >= ?
          AND close IS NOT NULL
        """
        params = (*asset_codes, start_date)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return {
                (row[0], row[1]): float(row[2])
                for row in cursor.fetchall()
                if row[2] is not None
            }

        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, params)
            return {
                (row[0], row[1]): float(row[2])
                for row in cursor.fetchall()
                if row[2] is not None
            }

    def get_fund_nav_map(
        self,
        asset_codes: List[str],
        start_date: str,
        conn=None,
    ) -> Dict[Tuple[str, str], float]:
        """批量读取指定日期起的基金单位净值 map。"""
        if not asset_codes:
            return {}

        placeholders = self._build_placeholders(asset_codes)
        sql = f"""
        SELECT asset_code, trade_date, unit_nav
        FROM dat_fund_daily
        WHERE asset_code IN ({placeholders})
          AND trade_date >= ?
          AND unit_nav IS NOT NULL
        """
        params = (*asset_codes, start_date)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return {
                (row[0], row[1]): float(row[2])
                for row in cursor.fetchall()
                if row[2] is not None
            }

        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, params)
            return {
                (row[0], row[1]): float(row[2])
                for row in cursor.fetchall()
                if row[2] is not None
            }

    def get_index_market_count_by_date(self, trade_date: str) -> int:
        """获取指定交易日的 INDEX 行情总数"""
        sql = """
        SELECT COUNT(*)
        FROM dat_market_daily m
        JOIN sys_asset_meta meta ON m.asset_code = meta.asset_code
        WHERE m.trade_date = ?
          AND meta.asset_type = 'INDEX'
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (trade_date,))
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def get_index_market_page_by_date(self, trade_date: str, limit: int, offset: int) -> List[dict]:
        """获取指定交易日的 INDEX 行情分页数据"""
        sql = """
        SELECT
            m.trade_date AS trade_date,
            m.asset_code AS code,
            meta.asset_name AS name,
            m.close AS close,
            m.volume AS volume,
            m.amount AS amount
        FROM dat_market_daily m
        JOIN sys_asset_meta meta ON m.asset_code = meta.asset_code
        WHERE m.trade_date = ?
          AND meta.asset_type = 'INDEX'
        ORDER BY m.amount DESC
        LIMIT ? OFFSET ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (trade_date, limit, offset))
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def get_latest_price(self, asset_code: str) -> Optional[dict]:
        """
        获取资产最新收盘价
        :return: {'close': float, 'trade_date': str, 'name': str} 或 None
        """
        sql = """
        SELECT m.close, m.trade_date, COALESCE(a.asset_name, m.asset_code) as name
        FROM dat_market_daily m
        LEFT JOIN sys_asset_meta a ON m.asset_code = a.asset_code
        WHERE m.asset_code = ?
        ORDER BY m.trade_date DESC
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code,))
            row = cursor.fetchone()
            if row:
                return {
                    'close': row[0],
                    'trade_date': row[1],
                    'name': row[2]
                }
            return None

    def get_latest_prices_batch(self, asset_codes: List[str]) -> dict:
        """
        批量获取多个资产的最新收盘价
        :return: {asset_code: {'close': float, 'trade_date': str, 'name': str, ...}}
        """
        if not asset_codes:
            return {}

        rows = self._fetch_latest_asset_snapshots(
            "dat_market_daily",
            "m",
            asset_codes,
            """
            m.asset_code,
            m.close,
            m.high,
            m.low,
            m.volume,
            m.amount,
            m.trade_date,
            COALESCE(a.asset_name, m.asset_code) AS name
            """,
        )
        return self._rows_to_keyed_dict(
            rows,
            0,
            lambda row: {
                "close": row[1],
                "high": row[2],
                "low": row[3],
                "volume": row[4],
                "amount": row[5],
                "trade_date": row[6],
                "name": row[7],
            },
        )

    def get_latest_prices_batch_as_of(self, asset_codes: List[str], as_of_date: str) -> dict:
        """
        批量获取多个资产在指定日期及之前最近一个交易日的收盘价。

        :return: {asset_code: {'close': float, 'trade_date': str, 'name': str}}
        """
        if not asset_codes:
            return {}

        rows = self._fetch_latest_asset_snapshots(
            "dat_market_daily",
            "m",
            asset_codes,
            """
            m.asset_code,
            m.close,
            m.trade_date,
            COALESCE(a.asset_name, m.asset_code) AS name
            """,
            extra_conditions=["trade_date <= ?"],
            extra_params=(as_of_date,),
        )
        return self._rows_to_keyed_dict(
            rows,
            0,
            lambda row: {
                "close": row[1],
                "trade_date": row[2],
                "name": row[3],
            },
        )

    def get_latest_fund_navs_batch_as_of(self, asset_codes: List[str], as_of_date: str) -> dict:
        """
        批量获取多个资产在指定日期及之前最近一个交易日的基金净值。

        :return: {asset_code: {'close': float, 'trade_date': str, 'name': str}}
        """
        if not asset_codes:
            return {}

        rows = self._fetch_latest_asset_snapshots(
            "dat_fund_daily",
            "f",
            asset_codes,
            """
            f.asset_code,
            f.unit_nav,
            f.trade_date,
            COALESCE(a.asset_name, f.asset_code) AS name
            """,
            extra_conditions=["trade_date <= ?", "unit_nav IS NOT NULL"],
            extra_params=(as_of_date,),
        )
        return self._rows_to_keyed_dict(
            rows,
            0,
            lambda row: {
                "close": row[1],
                "trade_date": row[2],
                "name": row[3],
            },
            row_filter=lambda row: row[1] is not None,
        )

    def get_last_dates_batch(self, asset_codes: List[str]) -> dict:
        """
        批量获取多个资产的最新数据日期

        性能优化：将 N 次数据库查询合并为 1 次，性能提升约 60 倍
        
        :param asset_codes: 资产代码列表
        :return: {asset_code: last_date} 字典，未查询到的资产返回 None
        """
        if not asset_codes:
            return {}

        placeholders = self._build_placeholders(asset_codes)
        sql = f"""
        SELECT asset_code, MAX(trade_date) as last_date
        FROM dat_market_daily
        WHERE asset_code IN ({placeholders})
        GROUP BY asset_code
        """

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, asset_codes)
            result_dict = {row[0]: row[1] for row in cursor.fetchall()}

        return self._ensure_keys(result_dict, asset_codes)

    def upsert_daily_data(self, df: pd.DataFrame):
        """批量写入标准行情数据 (Upsert)"""
        if df.empty:
            return
        
        # 数据完整性校验
        required_columns = ['asset_code', 'trade_date', 'open', 'high',
                            'low', 'close', 'volume', 'amount', 'source_id',
                            'updated_at']
        missing_columns = set(required_columns) - set(df.columns)
        if missing_columns:
            raise ValidationError(
                f"Missing required columns: {missing_columns}"
            )
        
        # 校验必填字段不能为 NULL
        if df['asset_code'].isnull().any():
            raise ValidationError("asset_code contains NULL values")
        if df['trade_date'].isnull().any():
            raise ValidationError("trade_date contains NULL values")
        if df['source_id'].isnull().any():
            raise ValidationError("source_id contains NULL values")
        invalid_sources = sorted(
            source_id
            for source_id in df['source_id'].dropna().unique()
            if source_id not in DataSource.ASSET_ROUTE_VALID
        )
        if invalid_sources:
            raise ValidationError(f"Invalid source_id values: {invalid_sources}")
        
        # 性能优化：使用 itertuples() 替代 iterrows()，性能提升约 100 倍
        # 空值处理：将 NaN 转换为 None（SQLite NULL）
        columns = ['asset_code', 'trade_date', 'open', 'high', 'low',
                   'close', 'volume', 'amount', 'source_id', 'updated_at']
        
        # 将 NaN 转换为 None，确保 DataFrame 中的 NaN 在数据库中存储为 NULL
        df_clean = df[columns].where(pd.notnull(df[columns]), None)
        data_tuples = list(df_clean.itertuples(index=False, name=None))

        sql = """
        INSERT INTO dat_market_daily 
        (asset_code, trade_date, open, high, low, close, volume, amount, source_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_code, trade_date) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            amount=excluded.amount,
            source_id=excluded.source_id,
            updated_at=excluded.updated_at
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, data_tuples)

market_dao = MarketDAO()
