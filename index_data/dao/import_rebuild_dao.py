from __future__ import annotations

from typing import Optional

from dao.base_dao import BaseDAO


class ImportRebuildDAO(BaseDAO):
    """导入重建专用写库 DAO。"""

    @property
    def table_name(self) -> str:
        return "sys_account_fund"

    def upsert_import_account(
        self,
        account_no: str,
        account_name: str,
        broker_name: str,
        commission_rate: float,
        commission_min: float,
        stamp_duty_rate: float,
        conn=None,
    ) -> int:
        """导入重建专用账户 upsert。"""
        def _upsert(write_conn) -> int:
            cursor = write_conn.cursor()
            cursor.execute(
                "SELECT account_id FROM sys_account_fund WHERE account_no = ?",
                (account_no,),
            )
            row = cursor.fetchone()
            if row:
                account_id = int(row[0])
                cursor.execute(
                    """
                    UPDATE sys_account_fund
                    SET account_name = ?, broker_name = ?, commission_rate = ?,
                        commission_min = ?, stamp_duty_rate = ?,
                        updated_at = datetime('now', 'localtime')
                    WHERE account_id = ?
                    """,
                    (
                        account_name,
                        broker_name,
                        commission_rate,
                        commission_min,
                        stamp_duty_rate,
                        account_id,
                    ),
                )
                return account_id

            cursor.execute(
                """
                INSERT INTO sys_account_fund (
                    account_no, account_name, broker_name,
                    commission_rate, commission_min, stamp_duty_rate
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    account_no,
                    account_name,
                    broker_name,
                    commission_rate,
                    commission_min,
                    stamp_duty_rate,
                ),
            )
            return int(cursor.lastrowid)

        if conn is not None:
            return _upsert(conn)
        with self.db_engine.get_connection() as write_conn:
            return _upsert(write_conn)

    def clear_import_account_data(self, account_id: int, conn=None) -> None:
        """清空导入重建账户数据并重置当前缓存。"""
        def _clear(write_conn) -> None:
            for table_name in (
                "trade_order",
                "account_cash_flow",
                "dat_position",
                "dat_account_history",
                "log_trade_audit",
            ):
                write_conn.execute(f"DELETE FROM {table_name} WHERE account_id = ?", (account_id,))
            write_conn.execute(
                """
                UPDATE sys_account_fund
                SET cash_balance = 0,
                    total_deposit = 0,
                    total_withdraw = 0,
                    acc_profit = 0,
                    total_shares = 0,
                    updated_at = datetime('now', 'localtime')
                WHERE account_id = ?
                """,
                (account_id,),
            )

        if conn is not None:
            _clear(conn)
            return
        with self.db_engine.get_connection() as write_conn:
            _clear(write_conn)

    def upsert_import_asset_meta(
        self,
        asset_code: str,
        asset_name: str,
        exchange: str,
        listing_date: Optional[str],
        conn=None,
    ) -> None:
        """导入重建专用资产元数据 upsert。"""
        sql = """
        INSERT INTO sys_asset_meta (
            asset_code, asset_name, asset_type, exchange, listing_date,
            is_active, market_category
        ) VALUES (?, ?, 'ETF', ?, ?, 1, 'EXCHANGE')
        ON CONFLICT(asset_code) DO UPDATE SET
            asset_name = excluded.asset_name,
            exchange = COALESCE(excluded.exchange, sys_asset_meta.exchange),
            listing_date = COALESCE(excluded.listing_date, sys_asset_meta.listing_date),
            is_active = 1,
            market_category = 'EXCHANGE'
        """
        params = (asset_code, asset_name, exchange, listing_date)
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, params)


import_rebuild_dao = ImportRebuildDAO()
