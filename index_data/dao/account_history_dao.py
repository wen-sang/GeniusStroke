"""
账户历史数据访问层 (AccountHistory DAO)

管理 dat_account_history 表，记录账户每日净值快照。
"""
from typing import List, Dict, Any, Optional
from dao.base_dao import BaseDAO


class AccountHistoryDAO(BaseDAO):
    """账户历史数据访问对象"""

    HISTORY_COLUMNS = (
        "account_id",
        "trade_date",
        "cash_balance",
        "market_value",
        "total_asset",
        "total_deposit",
        "total_withdraw",
        "total_shares",
        "unit_net_value",
        "daily_return",
        "daily_return_rate",
        "net_investment",
        "total_pnl",
        "pnl_ratio",
        "cum_realized_pnl",
        "cum_unrealized_pnl",
        "cum_total_pnl",
        "account_xirr",
        "is_data_complete",
        "updated_at",
    )
    HISTORY_WRITE_COLUMNS = HISTORY_COLUMNS[:-1]
    
    @property
    def table_name(self) -> str:
        return "dat_account_history"

    def _build_history_select_sql(self, where_clause: str, order_clause: str) -> str:
        """构造账户历史通用查询 SQL。"""
        return f"""
        SELECT
            {self._join_columns(self.HISTORY_COLUMNS)}
        FROM {self.table_name}
        WHERE {where_clause}
        {order_clause}
        """

    def _build_history_values(self, row: Dict[str, Any]) -> tuple:
        """按统一字段顺序提取写入值。"""
        return tuple(row[column] for column in self.HISTORY_WRITE_COLUMNS)

    def _fetch_history_rows(
        self,
        where_clause: str,
        params: tuple,
        order_clause: str,
        conn=None,
    ) -> List[Dict]:
        """执行账户历史列表查询。"""
        sql = self._build_history_select_sql(where_clause, order_clause)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor, cursor.fetchall())

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def _fetch_history_row(
        self,
        where_clause: str,
        params: tuple,
        order_clause: str,
        conn=None,
    ) -> Optional[Dict]:
        """执行账户历史单行查询。"""
        sql = self._build_history_select_sql(where_clause, order_clause)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row) if row else None

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row) if row else None
    
    def upsert_history(self, account_id: int, trade_date: str,
                       cash_balance: float, market_value: float,
                       total_asset: float, total_deposit: float,
                       total_withdraw: float, total_shares: float,
                       unit_net_value: float = 1.0,
                       daily_return: float = 0,
                       daily_return_rate: float = 0,
                       net_investment: float = None,
                       total_pnl: float = None,
                       pnl_ratio: float = None,
                       cum_realized_pnl: float = 0,
                       cum_unrealized_pnl: float = 0,
                       cum_total_pnl: float = 0,
                       account_xirr: float = 0,
                       is_data_complete: int = 0,
                       conn=None) -> None:
        """
        创建或更新账户历史记录
        
        :param account_id: 账户ID
        :param trade_date: 交易日期 YYYY-MM-DD
        :param cash_balance: 当日现金余额
        :param market_value: 当日持仓市值
        :param total_asset: 总资产 = cash_balance + market_value
        :param total_deposit: 截止当日累计入金
        :param total_withdraw: 截止当日累计出金
        :param total_shares: 当日总份额
        :param unit_net_value: 单位净值 = total_asset / total_shares
        :param daily_return: 当日盈亏额
        :param net_investment: 净投入 = total_deposit - total_withdraw
        :param total_pnl: 总盈亏 = total_asset - net_investment
        :param pnl_ratio: 收益率 = total_pnl / net_investment
        """
        # 自动计算可推导字段
        if net_investment is None:
            net_investment = total_deposit - total_withdraw
        if total_pnl is None:
            total_pnl = total_asset - net_investment
        if pnl_ratio is None:
            pnl_ratio = total_pnl / net_investment if net_investment > 0 else 0
        
        sql = """
        INSERT INTO dat_account_history (
            account_id, trade_date, cash_balance, market_value,
            total_asset, total_deposit, total_withdraw, total_shares,
            unit_net_value, daily_return, daily_return_rate, net_investment,
            total_pnl, pnl_ratio, cum_realized_pnl, cum_unrealized_pnl,
            cum_total_pnl, account_xirr, is_data_complete, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(account_id, trade_date) DO UPDATE SET
            cash_balance = excluded.cash_balance,
            market_value = excluded.market_value,
            total_asset = excluded.total_asset,
            total_deposit = excluded.total_deposit,
            total_withdraw = excluded.total_withdraw,
            total_shares = excluded.total_shares,
            unit_net_value = excluded.unit_net_value,
            daily_return = excluded.daily_return,
            daily_return_rate = excluded.daily_return_rate,
            net_investment = excluded.net_investment,
            total_pnl = excluded.total_pnl,
            pnl_ratio = excluded.pnl_ratio,
            cum_realized_pnl = excluded.cum_realized_pnl,
            cum_unrealized_pnl = excluded.cum_unrealized_pnl,
            cum_total_pnl = excluded.cum_total_pnl,
            account_xirr = excluded.account_xirr,
            is_data_complete = excluded.is_data_complete,
            updated_at = excluded.updated_at
        """
        params = (
            account_id, trade_date, cash_balance, market_value,
            total_asset, total_deposit, total_withdraw, total_shares,
            unit_net_value, daily_return, daily_return_rate, net_investment,
            total_pnl, pnl_ratio, cum_realized_pnl, cum_unrealized_pnl,
            cum_total_pnl, account_xirr, is_data_complete
        )
        if conn is not None:
            conn.execute(sql, params)
            return
        self._execute_update(sql, params)

    def replace_history_rows(self, account_id: int, rows: List[Dict], from_date: str, conn=None) -> None:
        """用新结果替换指定日期起的账户历史。"""
        if conn is None:
            with self.db_engine.get_connection() as write_conn:
                self.replace_history_rows(account_id, rows, from_date, conn=write_conn)
            return

        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM dat_account_history WHERE account_id = ? AND trade_date >= ?",
            (account_id, from_date),
        )
        if not rows:
            return

        cursor.executemany(
            """
            INSERT INTO dat_account_history (
                account_id, trade_date, cash_balance, market_value, total_asset,
                total_deposit, total_withdraw, total_shares, unit_net_value,
                daily_return, daily_return_rate, net_investment, total_pnl, pnl_ratio,
                cum_realized_pnl, cum_unrealized_pnl, cum_total_pnl, account_xirr,
                is_data_complete, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            [self._build_history_values(row) for row in rows],
        )
    
    def get_history(self, account_id: int,
                    start_date: str = None,
                    end_date: str = None,
                    conn=None) -> List[Dict]:
        """
        获取账户历史记录
        
        :param account_id: 账户ID
        :param start_date: 开始日期 (可选)
        :param end_date: 结束日期 (可选)
        :return: 历史记录列表 (按日期升序)
        """
        where_clause = "account_id = ?"
        params = [account_id]
        
        if start_date:
            where_clause += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            where_clause += " AND trade_date <= ?"
            params.append(end_date)
        return self._fetch_history_rows(
            where_clause,
            tuple(params),
            "ORDER BY trade_date ASC",
            conn=conn,
        )

    def get_complete_history(self, account_id: int, conn=None) -> List[Dict]:
        """获取账户完整正式收盘历史。"""
        return self._fetch_history_rows(
            "account_id = ? AND is_data_complete = 1",
            (account_id,),
            "ORDER BY trade_date ASC",
            conn=conn,
        )
    
    def get_latest_history(self, account_id: int, conn=None) -> Optional[Dict]:
        """获取最新的历史记录"""
        return self._fetch_history_row(
            "account_id = ?",
            (account_id,),
            "ORDER BY trade_date DESC\n        LIMIT 1",
            conn=conn,
        )

    def get_latest_complete_history(self, account_id: int, conn=None) -> Optional[Dict]:
        """获取最新的正式收盘历史记录。"""
        return self._fetch_history_row(
            "account_id = ? AND is_data_complete = 1",
            (account_id,),
            "ORDER BY trade_date DESC\n        LIMIT 1",
            conn=conn,
        )

    def get_history_by_date(self, account_id: int, trade_date: str, conn=None) -> Optional[Dict]:
        """获取账户指定日期的一条历史记录。"""
        return self._fetch_history_row(
            "account_id = ? AND trade_date = ?",
            (account_id, trade_date),
            "LIMIT 1",
            conn=conn,
        )

    def get_latest_complete_history_before(
        self,
        account_id: int,
        trade_date: str,
        conn=None,
    ) -> Optional[Dict]:
        """获取指定日期之前最近的一条正式收盘历史。"""
        return self._fetch_history_row(
            "account_id = ? AND trade_date < ? AND is_data_complete = 1",
            (account_id, trade_date),
            "ORDER BY trade_date DESC\n        LIMIT 1",
            conn=conn,
        )
    
    def get_previous_day(self, account_id: int, trade_date: str, conn=None) -> Optional[Dict]:
        """获取指定日期前一天的记录"""
        return self._fetch_history_row(
            "account_id = ? AND trade_date < ?",
            (account_id, trade_date),
            "ORDER BY trade_date DESC\n        LIMIT 1",
            conn=conn,
        )


# 单例
account_history_dao = AccountHistoryDAO()
