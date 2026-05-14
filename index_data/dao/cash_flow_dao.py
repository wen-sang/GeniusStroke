"""
资金流水数据访问层 (CashFlow DAO)

管理 account_cash_flow 表的新增与查询。
"""
from typing import Dict, List, Optional

from dao.base_dao import BaseDAO
from core.trade.models import CashFlow


class CashFlowDAO(BaseDAO):
    """资金流水数据访问对象"""

    @property
    def table_name(self) -> str:
        return "account_cash_flow"

    def insert_cash_flow(self, cash_flow: CashFlow, conn=None) -> int:
        """插入一笔资金流水并返回 flow_id。"""
        sql = """
        INSERT INTO account_cash_flow (
            account_id, biz_date, flow_type, direction, amount, status, remark, source_type, source_ref_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'))
        """
        params = (
            cash_flow.account_id,
            cash_flow.biz_date,
            cash_flow.flow_type,
            cash_flow.direction,
            cash_flow.amount,
            cash_flow.status,
            cash_flow.remark,
            cash_flow.source_type,
            cash_flow.source_ref_id,
        )
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.lastrowid

        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, params)
            return cursor.lastrowid

    def list_cash_flows(
        self,
        account_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        flow_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """按账户查询资金流水。"""
        sql = f"""
        SELECT
            flow_id, account_id, biz_date, flow_type, direction, amount, status, remark,
            source_type, source_ref_id, created_at, updated_at
        FROM {self.table_name}
        WHERE account_id = ?
          AND COALESCE(status, 'ACTIVE') = 'ACTIVE'
        """
        params: List[object] = [account_id]

        if start_date:
            sql += " AND biz_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND biz_date <= ?"
            params.append(end_date)
        if flow_type:
            sql += " AND flow_type = ?"
            params.append(flow_type)

        sql += " ORDER BY biz_date DESC, flow_id DESC LIMIT ?"
        params.append(limit)

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def sum_external_cash_delta(
        self,
        account_id: int,
        start_date: str,
        end_date: str,
        conn=None,
    ) -> float:
        """汇总指定区间内外部入金/出金净额。"""
        if conn is not None:
            return self._sum_external_cash_delta_with_connection(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
                conn=conn,
            )

        with self.db_engine.get_connection(readonly=True) as ro_conn:
            return self._sum_external_cash_delta_with_connection(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
                conn=ro_conn,
            )

    def _sum_external_cash_delta_with_connection(
        self,
        account_id: int,
        start_date: str,
        end_date: str,
        conn,
    ) -> float:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(account_cash_flow)")
        has_status_column = any(row[1] == "status" for row in cursor.fetchall())
        status_filter = "AND COALESCE(status, 'ACTIVE') = 'ACTIVE'" if has_status_column else ""
        cursor.execute(
            f"""
            SELECT direction, amount
            FROM {self.table_name}
            WHERE account_id = ?
              AND biz_date > ?
              AND biz_date <= ?
              {status_filter}
              AND flow_type IN ('DEPOSIT', 'WITHDRAW')
            """,
            (account_id, start_date, end_date),
        )
        total = 0.0
        for direction, amount in cursor.fetchall():
            signed = float(amount or 0.0)
            total += signed if direction == "IN" else -signed
        return total


cash_flow_dao = CashFlowDAO()
