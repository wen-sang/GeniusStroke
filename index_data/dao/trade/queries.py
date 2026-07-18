# 文件: dao/trade/queries.py
"""持仓与绩效查询：可卖批次、持仓汇总、已实现盈亏、绩效卖单。"""
from typing import Optional, Dict, List


class TradePositionQueryMixin:
    def get_available_lots(self, asset_code: str, account_id: int = 1) -> List[Dict]:
        """
        获取某标的的可卖批次
        :return: 按买入日期升序排列的批次列表
        """
        sql = """
        SELECT order_id, trade_time as buy_date, price as buy_price,
               remain_vol, target_rate
        FROM trade_order
        WHERE asset_code = ? AND account_id = ?
              AND side = 'BUY' AND status = 1 AND remain_vol > 0
        ORDER BY trade_time ASC
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code, account_id))
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def get_positions_summary(self, account_id: int = 1, page: int = 1, page_size: int = 60) -> List[Dict]:
        """
        获取持仓汇总 (按标的聚合)
        """
        offset = (page - 1) * page_size
        sql = """
        SELECT
            o.asset_code,
            COALESCE(m.asset_name, o.asset_code) as asset_name,
            COALESCE(m.asset_type, '') as asset_type,
            SUM(o.remain_vol) as total_volume,
            SUM(o.remain_vol * o.price) / NULLIF(SUM(o.remain_vol), 0) as avg_cost,
            SUM(o.remain_vol * o.target_rate) / NULLIF(SUM(o.remain_vol), 0) as avg_target_rate
        FROM trade_order o
        LEFT JOIN sys_asset_meta m ON o.asset_code = m.asset_code
        WHERE o.account_id = ? AND o.side = 'BUY' AND o.status = 1 AND o.remain_vol > 0
        GROUP BY o.asset_code
        ORDER BY total_volume DESC
        LIMIT ? OFFSET ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id, page_size, offset))
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def get_position_count(self, account_id: int = 1) -> int:
        """获取持仓标的总数。"""
        sql = """
        SELECT COUNT(*) FROM (
            SELECT o.asset_code
            FROM trade_order o
            WHERE o.account_id = ? AND o.side = 'BUY' AND o.status = 1 AND o.remain_vol > 0
            GROUP BY o.asset_code
        ) t
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            return cursor.fetchone()[0]

    def get_realized_pnl_by_asset(self, account_id: int = 1) -> Dict[str, float]:
        """获取各标的历史已实现收益汇总。"""
        sql = """
        SELECT asset_code, SUM(COALESCE(realized_pnl, 0)) AS realized_pnl
        FROM trade_order
        WHERE account_id = ? AND side = 'SELL' AND status = 1
        GROUP BY asset_code
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            rows = cursor.fetchall()
            return {
                str(asset_code): float(realized_pnl or 0.0)
                for asset_code, realized_pnl in rows
                if asset_code
            }

    # ========== 审计日志 ==========

    def count_performance_trades(self, account_id: int, start_date: Optional[str] = None, conn=None) -> int:
        """统计绩效口径的有效普通买卖订单数。"""
        sql = """
        SELECT COUNT(*)
        FROM trade_order
        WHERE account_id = ?
          AND side IN ('BUY', 'SELL')
          AND status = 1
          AND COALESCE(volume, 0) > 0
          AND COALESCE(source_type, 'MANUAL') != 'CORPORATE_ACTION'
          AND COALESCE(order_type, '') NOT IN ('SPLIT_ADJUST', 'DIVIDEND_REINVEST_BUY')
        """
        params: list[object] = [account_id]
        if start_date:
            sql += " AND substr(trade_time, 1, 10) >= ?"
            params.append(start_date)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return int(cursor.fetchone()[0] or 0)
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, tuple(params))
            return int(cursor.fetchone()[0] or 0)

    def list_performance_sell_orders(
        self,
        account_id: int,
        start_date: Optional[str] = None,
        conn=None,
    ) -> List[Dict]:
        """获取绩效口径的有效普通卖单样本。"""
        sql = """
        SELECT
            sell.order_id,
            sell.trade_time,
            buy.trade_time AS buy_trade_time,
            sell.realized_pnl
        FROM trade_order sell
        LEFT JOIN trade_order buy ON buy.order_id = sell.link_order_id
        WHERE sell.account_id = ?
          AND sell.side = 'SELL'
          AND sell.status = 1
          AND COALESCE(sell.volume, 0) > 0
          AND sell.link_order_id IS NOT NULL
          AND COALESCE(sell.source_type, 'MANUAL') != 'CORPORATE_ACTION'
          AND COALESCE(sell.order_type, '') != 'SPLIT_ADJUST'
        ORDER BY sell.trade_time ASC, sell.order_id ASC
        """
        params: list[object] = [account_id]
        if start_date:
            sql = sql.replace("ORDER BY", "AND substr(sell.trade_time, 1, 10) >= ?\n        ORDER BY")
            params.append(start_date)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return self._rows_to_dicts(cursor, cursor.fetchall())
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, tuple(params))
            return self._rows_to_dicts(cursor, cursor.fetchall())
