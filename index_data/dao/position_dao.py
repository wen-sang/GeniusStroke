"""
持仓数据访问层 (Position DAO)

管理 dat_position 表的 CRUD 操作。
"""
from typing import List, Dict, Any, Optional
from dao.base_dao import BaseDAO
from utils.logger import logger


class PositionDAO(BaseDAO):
    """持仓数据访问对象"""
    
    @property
    def table_name(self) -> str:
        return "dat_position"
    
    def upsert_position(self, account_id: int, asset_code: str,
                        total_volume: float, available_volume: float,
                        cost_price: float, cost_amount: float,
                        market_price: float = 0, market_value: float = 0,
                        unrealized_pnl: float = 0, pnl_ratio: float = 0) -> None:
        """
        创建或更新持仓记录
        
        :param account_id: 账户ID
        :param asset_code: 资产代码
        :param total_volume: 总持仓份额
        :param available_volume: 可卖份额
        :param cost_price: 成本单价
        :param cost_amount: 成本金额
        :param market_price: 最新市价
        :param market_value: 持仓市值
        :param unrealized_pnl: 浮动盈亏
        :param pnl_ratio: 盈亏比例
        """
        sql = """
        INSERT INTO dat_position (
            account_id, asset_code, total_volume, available_volume,
            cost_price, cost_amount, market_price, market_value,
            unrealized_pnl, pnl_ratio, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(account_id, asset_code) DO UPDATE SET
            total_volume = excluded.total_volume,
            available_volume = excluded.available_volume,
            cost_price = excluded.cost_price,
            cost_amount = excluded.cost_amount,
            market_price = excluded.market_price,
            market_value = excluded.market_value,
            unrealized_pnl = excluded.unrealized_pnl,
            pnl_ratio = excluded.pnl_ratio,
            updated_at = excluded.updated_at
        """
        self._execute_update(sql, (
            account_id, asset_code, total_volume, available_volume,
            cost_price, cost_amount, market_price, market_value,
            unrealized_pnl, pnl_ratio
        ))
    
    def get_position(self, account_id: int, asset_code: str) -> Optional[Dict]:
        """获取单个持仓"""
        sql = f"""
        SELECT
            account_id, asset_code, total_volume, available_volume,
            cost_price, cost_amount, market_price, market_value,
            unrealized_pnl, pnl_ratio, updated_at
        FROM {self.table_name}
        WHERE account_id = ? AND asset_code = ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id, asset_code))
            row = cursor.fetchone()
            return self._row_to_dict(cursor, row) if row else None
    
    def get_positions_by_account(self, account_id: int) -> List[Dict]:
        """获取账户所有持仓"""
        sql = f"""
        SELECT
            account_id, asset_code, total_volume, available_volume,
            cost_price, cost_amount, market_price, market_value,
            unrealized_pnl, pnl_ratio, updated_at
        FROM {self.table_name}
        WHERE account_id = ? AND total_volume > 0
        ORDER BY asset_code
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def get_active_account_holding_codes(self) -> Dict[int, List[str]]:
        """获取所有当前有持仓账户的持仓代码集合。"""
        sql = f"""
        SELECT account_id, asset_code
        FROM {self.table_name}
        WHERE total_volume > 0
        ORDER BY account_id, asset_code
        """
        result: Dict[int, List[str]] = {}
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            for account_id, asset_code in cursor.fetchall():
                result.setdefault(int(account_id), []).append(asset_code)
        return result

    def get_account_position_valuation(self, account_id: int, conn=None) -> Dict[str, float]:
        """获取账户当前持仓市值与浮动盈亏聚合。"""
        sql = f"""
        SELECT
            COALESCE(SUM(market_value), 0) AS market_value,
            COALESCE(SUM(unrealized_pnl), 0) AS floating_pnl
        FROM {self.table_name}
        WHERE account_id = ?
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            row = cursor.fetchone()
        else:
            with self.db_engine.get_connection(readonly=True) as ro_conn:
                cursor = ro_conn.cursor()
                cursor.execute(sql, (account_id,))
                row = cursor.fetchone()

        return {
            "market_value": float(row[0] or 0.0) if row else 0.0,
            "floating_pnl": float(row[1] or 0.0) if row else 0.0,
        }

    def replace_account_positions(self, account_id: int, positions: List[Dict], conn=None) -> None:
        """按账户替换当前持仓缓存。"""
        def _replace(write_conn) -> None:
            write_conn.execute("DELETE FROM dat_position WHERE account_id = ?", (account_id,))
            if not positions:
                return
            write_conn.executemany(
                """
                INSERT INTO dat_position (
                    account_id, asset_code, total_volume, available_volume,
                    cost_price, cost_amount, market_price, market_value,
                    unrealized_pnl, pnl_ratio, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                [
                    (
                        item["account_id"],
                        item["asset_code"],
                        item["total_volume"],
                        item["available_volume"],
                        item["cost_price"],
                        item["cost_amount"],
                        item["market_price"],
                        item["market_value"],
                        item["unrealized_pnl"],
                        item["pnl_ratio"],
                    )
                    for item in positions
                ],
            )

        if conn is not None:
            _replace(conn)
            return
        with self.db_engine.get_connection() as write_conn:
            _replace(write_conn)
    
    def update_market_data(self, account_id: int, asset_code: str,
                           market_price: float) -> None:
        """
        更新持仓市价及市值
        
        自动计算 market_value, unrealized_pnl, pnl_ratio
        """
        position = self.get_position(account_id, asset_code)
        if not position or position['total_volume'] <= 0:
            return
        
        volume = position['total_volume']
        cost_amount = position['cost_amount']
        
        market_value = market_price * volume
        unrealized_pnl = market_value - cost_amount
        pnl_ratio = unrealized_pnl / cost_amount if cost_amount > 0 else 0
        
        sql = """
        UPDATE dat_position SET 
            market_price = ?,
            market_value = ?,
            unrealized_pnl = ?,
            pnl_ratio = ?,
            updated_at = datetime('now', 'localtime')
        WHERE account_id = ? AND asset_code = ?
        """
        self._execute_update(sql, (
            market_price, market_value, unrealized_pnl, pnl_ratio,
            account_id, asset_code
        ))
    
    def delete_position(self, account_id: int, asset_code: str) -> int:
        """删除持仓记录 (清仓时使用)"""
        sql = f"DELETE FROM {self.table_name} WHERE account_id = ? AND asset_code = ?"
        return self._execute_update(sql, (account_id, asset_code))
    
    def clear_zero_positions(self, account_id: int) -> int:
        """清除零持仓记录"""
        sql = f"DELETE FROM {self.table_name} WHERE account_id = ? AND total_volume <= 0"
        return self._execute_update(sql, (account_id,))


# 单例
position_dao = PositionDAO()
