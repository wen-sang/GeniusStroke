# 文件: dao/trade/orders.py
"""交易订单：单号生成、插入、查询、批量回填与台账列表。"""
from typing import TYPE_CHECKING, Optional, Dict, List

if TYPE_CHECKING:
    from core.trade.models import Order


class TradeOrderMixin:
    def generate_order_no(self, trade_date: str, conn=None) -> str:
        """
        生成订单业务编号

        格式: ORD{YYYYMMDD}{3位序号}
        示例: ORD20260201001

        :param trade_date: 交易日期 YYYY-MM-DD
        :return: 订单编号
        """
        date_part = trade_date.replace('-', '')[:8]
        prefix = f"ORD{date_part}"

        # 查询当日已有最大序号
        sql = """
        SELECT order_no FROM trade_order
        WHERE order_no LIKE ? || '%'
        ORDER BY order_no DESC
        LIMIT 1
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (prefix,))
            row = cursor.fetchone()
        else:
            with self.db_engine.get_connection(readonly=True) as ro_conn:
                cursor = ro_conn.cursor()
                cursor.execute(sql, (prefix,))
                row = cursor.fetchone()

        if row and row[0]:
            # 提取序号部分并递增
            last_no = row[0]
            seq = int(last_no[-3:]) + 1
        else:
            seq = 1

        return f"{prefix}{seq:03d}"

    def insert_order(self, order: "Order", order_no: str = None, conn=None) -> int:
        """
        插入订单，返回 order_id

        :param order: 订单对象
        :param order_no: 业务编号 (可选，不传则自动生成)
        :return: order_id
        """
        # 自动生成 order_no
        if not order_no:
            trade_date = order.trade_time[:10]  # YYYY-MM-DD
            order_no = self.generate_order_no(trade_date, conn=conn)
        order_type = order.order_type or self._infer_order_type(order.side, order.source_type)

        sql = """
        INSERT INTO trade_order (
            order_no, account_id, asset_code, trade_time, side, order_type, price, volume, amount,
            commission, transfer_fee, tax, remain_vol, link_order_id, target_rate,
            realized_pnl, status, remark, source_type, source_ref_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (
                order_no, order.account_id, order.asset_code, order.trade_time,
                order.side, order_type, order.price, order.volume, order.amount,
                order.commission, order.transfer_fee, order.tax, order.remain_vol,
                order.link_order_id, order.target_rate, order.realized_pnl,
                order.status, order.remark, order.source_type, order.source_ref_id
            ))
            return cursor.lastrowid
        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, (
                order_no, order.account_id, order.asset_code, order.trade_time,
                order.side, order_type, order.price, order.volume, order.amount,
                order.commission, order.transfer_fee, order.tax, order.remain_vol,
                order.link_order_id, order.target_rate, order.realized_pnl,
                order.status, order.remark, order.source_type, order.source_ref_id
            ))
            return cursor.lastrowid

    def get_order(self, order_id: int, conn=None) -> Optional["Order"]:
        """获取单个订单"""
        from core.trade.models import Order

        sql = """
        SELECT
            order_id, order_no, account_id, asset_code, trade_time,
            side, order_type, price, volume, amount, commission, transfer_fee, tax,
            remain_vol, link_order_id, target_rate, realized_pnl,
            status, remark, source_type, source_ref_id, updated_at, created_at
        FROM trade_order
        WHERE order_id = ?
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (order_id,))
            row = cursor.fetchone()
            if row:
                data = self._row_to_dict(cursor, row)
                return Order.from_dict(data)
            return None
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (order_id,))
            row = cursor.fetchone()
            if row:
                data = self._row_to_dict(cursor, row)
                return Order.from_dict(data)
            return None

    def get_order_by_manual_source_ref(self, account_id: int, source_ref_id: str, conn=None) -> Optional["Order"]:
        """按手工订单幂等键获取有效订单。"""
        from core.trade.models import Order

        sql = """
        SELECT
            order_id, order_no, account_id, asset_code, trade_time,
            side, order_type, price, volume, amount, commission, transfer_fee, tax,
            remain_vol, link_order_id, target_rate, realized_pnl,
            status, remark, source_type, source_ref_id, updated_at, created_at
        FROM trade_order
        WHERE account_id = ?
          AND source_type = 'MANUAL'
          AND source_ref_id = ?
          AND status = 1
        ORDER BY order_id ASC
        LIMIT 1
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id, source_ref_id))
            row = cursor.fetchone()
            if row:
                data = self._row_to_dict(cursor, row)
                return Order.from_dict(data)
            return None
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (account_id, source_ref_id))
            row = cursor.fetchone()
            if row:
                data = self._row_to_dict(cursor, row)
                return Order.from_dict(data)
            return None

    def check_order_exists(self, asset_code: str, trade_date: str,
                           price: float, volume: float) -> bool:
        """
        检查订单是否存在 (用于导入查重: 日期+代码+价格+份数)
        :param trade_date: 取日期部分 YYYY-MM-DD
        """
        # 注意: DB中 trade_time 是 YYYY-MM-DD HH:MM:SS
        # 价格比较允许微小误差
        sql = """
        SELECT count(*) FROM trade_order
        WHERE asset_code = ?
          AND side = 'BUY'
          AND trade_time LIKE ? || '%'
          AND ABS(price - ?) < 0.0001
          AND ABS(volume - ?) < 0.0001
          AND status = 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code, trade_date, price, volume))
            count = cursor.fetchone()[0]
            return count > 0

    def bulk_update_buy_order_remain_vol(self, updates: List[tuple], conn=None) -> None:
        """批量更新买入订单剩余份额。"""
        if not updates:
            return
        sql = """
        UPDATE trade_order
        SET remain_vol = ?, updated_at = datetime('now', 'localtime')
        WHERE order_id = ?
        """
        if conn is not None:
            conn.executemany(sql, updates)
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.executemany(sql, updates)

    def bulk_update_sell_order_realized_pnl(self, updates: List[tuple], conn=None) -> None:
        """批量更新卖出订单已实现收益。"""
        if not updates:
            return
        sql = """
        UPDATE trade_order
        SET realized_pnl = ?, updated_at = datetime('now', 'localtime')
        WHERE order_id = ?
        """
        if conn is not None:
            conn.executemany(sql, updates)
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.executemany(sql, updates)

    def update_order_details(self, order_id: int, trade_time: str, side: str,
                             price: float, volume: float, amount: float,
                             commission: float, transfer_fee: float,
                             tax: float, conn=None) -> None:
        """
        更新订单详情 (主要用于数据修正流水)
        注: 不更新 link_order_id、target_rate, realized_pnl 等联动字段, 仅更新本身核心数据
        """
        sql = """
        UPDATE trade_order
        SET trade_time = ?, side = ?, price = ?, volume = ?, amount = ?,
            commission = ?, transfer_fee = ?, tax = ?,
            updated_at = datetime('now', 'localtime')
        WHERE order_id = ?
        """
        if conn is not None:
            conn.execute(sql, (
                trade_time, side, price, volume, amount, commission,
                transfer_fee, tax, order_id,
            ))
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, (
                trade_time, side, price, volume, amount, commission,
                transfer_fee, tax, order_id,
            ))

    def get_orders(self, account_id: int = 1, page: int = 1, page_size: int = 60) -> List[Dict]:
        """
        分页获取订单记录
        """
        offset = (page - 1) * page_size
        sql = """
        SELECT
            o.order_id, o.order_no, o.account_id, o.asset_code, o.trade_time,
            o.side, o.order_type, o.price, o.volume, o.amount, o.commission, o.transfer_fee, o.tax,
            o.remain_vol, o.link_order_id, o.target_rate, o.realized_pnl,
            o.status, o.remark, o.source_type, o.source_ref_id, o.updated_at, o.created_at,
            m.asset_name, m.asset_type
        FROM trade_order o
        LEFT JOIN sys_asset_meta m ON o.asset_code = m.asset_code
        WHERE o.account_id = ?
        ORDER BY o.trade_time DESC
        LIMIT ? OFFSET ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id, page_size, offset))
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def list_orders_for_ledger(self, account_id: int = 1, conn=None) -> List[Dict]:
        sql = """
        SELECT
            o.order_id, o.order_no, o.account_id, o.asset_code, o.trade_time,
            o.side, o.order_type, o.price, o.volume, o.amount, o.commission, o.transfer_fee, o.tax,
            o.remain_vol, o.link_order_id, o.target_rate, o.realized_pnl,
            o.status, o.remark, o.source_type, o.source_ref_id, o.updated_at, o.created_at,
            COALESCE(m.asset_name, o.asset_code) AS asset_name,
            m.asset_type
        FROM trade_order o
        LEFT JOIN sys_asset_meta m ON o.asset_code = m.asset_code
        WHERE o.account_id = ?
          AND COALESCE(o.source_type, 'MANUAL') != 'CORPORATE_ACTION'
        ORDER BY o.trade_time DESC, o.order_id DESC
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            return self._rows_to_dicts(cursor, cursor.fetchall())
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (account_id,))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def get_order_count(self, account_id: int = 1) -> int:
        """获取订单总数"""
        sql = "SELECT count(*) FROM trade_order WHERE account_id = ?"
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            return cursor.fetchone()[0]

    @staticmethod
    def _infer_order_type(side: str, source_type: Optional[str]) -> Optional[str]:
        normalized_side = (side or "").upper()
        normalized_source = (source_type or "").upper()
        if normalized_source == "CORPORATE_ACTION" and normalized_side == "BUY":
            return "DIVIDEND_REINVEST_BUY"
        if normalized_source == "CORPORATE_ACTION" and normalized_side == "ADJUST":
            return "SPLIT_ADJUST"
        if normalized_side == "BUY":
            return "MANUAL_BUY"
        if normalized_side == "SELL":
            return "MANUAL_SELL"
        return None


# 单例
