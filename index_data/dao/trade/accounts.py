# 文件: dao/trade/accounts.py
"""交易账户：CRUD、资金与累计字段更新、汇总刷新、首笔事实日期。"""
from typing import Optional, Dict, List


class TradeAccountMixin:
    def get_account(self, account_id: int = 1, conn=None) -> Optional[Dict]:
        """获取账户信息"""
        sql = """
        SELECT
            account_id, account_no, account_name, broker_name,
            commission_rate, commission_min, stamp_duty_rate,
            cash_balance, total_deposit, total_withdraw,
            total_shares, acc_profit, updated_at
        FROM sys_account_fund
        WHERE account_id = ?
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (account_id,))
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)

    def get_or_create_account(self, account_id: int = 1, conn=None) -> Dict:
        """获取账户，如果不存在则创建默认账户"""
        account = self.get_account(account_id, conn=conn)
        if account:
            return account

        # 创建默认账户
        sql = """
        INSERT INTO sys_account_fund (account_name, cash_balance)
        VALUES ('Default', 0)
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql)
            new_id = cursor.lastrowid
        else:
            with self.db_engine.get_connection() as write_conn:
                cursor = write_conn.cursor()
                cursor.execute(sql)
                new_id = cursor.lastrowid

        return self.get_account(new_id, conn=conn)

    def list_accounts(self, conn=None) -> List[Dict]:
        """获取账户列表（仅切换视图所需最小字段）。"""
        sql = """
        SELECT account_id, account_name
        FROM sys_account_fund
        WHERE account_id != 0
        ORDER BY account_id
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def count_accounts(self, conn=None) -> int:
        """获取账户总数。"""
        sql = "SELECT COUNT(*) FROM sys_account_fund WHERE account_id != 0"
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql)
            return int(cursor.fetchone()[0] or 0)
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql)
            return int(cursor.fetchone()[0] or 0)

    def get_first_account(self, conn=None) -> Optional[Dict]:
        """获取排序后的第一个账户。"""
        sql = """
        SELECT account_id, account_no, account_name, broker_name,
               commission_rate, commission_min, stamp_duty_rate,
               cash_balance, total_deposit, total_withdraw,
               total_shares, acc_profit, updated_at
        FROM sys_account_fund
        WHERE account_id != 0
        ORDER BY account_id
        LIMIT 1
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)

    def get_account_by_trimmed_name(self, account_name: str, conn=None) -> Optional[Dict]:
        """按去首尾空格后的账户名称查询。"""
        sql = """
        SELECT
            account_id, account_no, account_name, broker_name,
            commission_rate, commission_min, stamp_duty_rate,
            cash_balance, total_deposit, total_withdraw,
            total_shares, acc_profit, updated_at
        FROM sys_account_fund
        WHERE TRIM(account_name) = ?
        LIMIT 1
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (account_name,))
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (account_name,))
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row)

    def create_account(self, account_name: str, conn=None) -> Dict:
        """创建账户并返回完整账户信息。"""
        sql = """
        INSERT INTO sys_account_fund (account_name, cash_balance)
        VALUES (?, 0)
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (account_name,))
            return self.get_account(cursor.lastrowid, conn=conn)
        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, (account_name,))
            return self.get_account(cursor.lastrowid, conn=write_conn)

    def update_account_name(self, account_id: int, account_name: str, conn=None) -> None:
        """更新账户名称。"""
        sql = """
        UPDATE sys_account_fund
        SET account_name = ?,
            updated_at = datetime('now', 'localtime')
        WHERE account_id = ?
        """
        if conn is not None:
            conn.execute(sql, (account_name, account_id))
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, (account_name, account_id))

    def has_account_asset_data(self, account_id: int, conn=None) -> bool:
        """校验账户是否存在任一资产相关数据。"""
        sql = """
        WITH refs AS (
            SELECT 1 FROM trade_order WHERE account_id = ?
            UNION ALL
            SELECT 1 FROM account_cash_flow WHERE account_id = ?
            UNION ALL
            SELECT 1 FROM dat_position WHERE account_id = ?
            UNION ALL
            SELECT 1 FROM dat_account_history WHERE account_id = ?
        )
        SELECT EXISTS(SELECT 1 FROM refs LIMIT 1)
        """
        params = (account_id, account_id, account_id, account_id)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return bool(cursor.fetchone()[0])
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, params)
            return bool(cursor.fetchone()[0])

    def delete_account(self, account_id: int, conn=None) -> None:
        """删除账户。"""
        sql = "DELETE FROM sys_account_fund WHERE account_id = ?"
        if conn is not None:
            conn.execute(sql, (account_id,))
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, (account_id,))

    def refresh_account_summary(
        self,
        account_id: int,
        cash_balance: float,
        total_deposit: float,
        total_withdraw: float,
        acc_profit: float,
        broker_name: Optional[str],
        conn=None,
    ) -> None:
        """覆盖刷新账户当前资金摘要。"""
        sql = """
        UPDATE sys_account_fund
        SET cash_balance = ?,
            total_deposit = ?,
            total_withdraw = ?,
            acc_profit = ?,
            total_shares = COALESCE((
                SELECT h.total_shares
                FROM dat_account_history h
                WHERE h.account_id = ?
                  AND h.is_data_complete = 1
                  AND h.total_shares IS NOT NULL
                ORDER BY h.trade_date DESC
                LIMIT 1
            ), total_shares),
            broker_name = COALESCE(?, broker_name),
            updated_at = datetime('now', 'localtime')
        WHERE account_id = ?
        """
        params = (
            cash_balance,
            total_deposit,
            total_withdraw,
            acc_profit,
            account_id,
            broker_name,
            account_id,
        )
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, params)

    def get_account_first_fact_date(self, account_id: int, conn=None) -> Optional[str]:
        """获取账户最早业务事实日期。"""
        sql = """
        WITH fact_dates AS (
            SELECT substr(trade_time, 1, 10) AS biz_date
            FROM trade_order
            WHERE account_id = ? AND status = 1
            UNION ALL
            SELECT biz_date
            FROM account_cash_flow
            WHERE account_id = ?
              AND COALESCE(status, 'ACTIVE') = 'ACTIVE'
        )
        SELECT MIN(biz_date) FROM fact_dates
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id, account_id))
            row = cursor.fetchone()
            return row[0] if row and row[0] else None
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (account_id, account_id))
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

    # ========== 持仓查询 ==========
