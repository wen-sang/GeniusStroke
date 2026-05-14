# dao/trade_dao.py - 交易数据访问层
"""
交易管理 DAO
v2.4.5: 支持订单 CRUD 和持仓查询
"""
from typing import TYPE_CHECKING, Dict, List, Optional

from dao.base_dao import BaseDAO

if TYPE_CHECKING:
    from core.trade.models import Order


class TradeDAO(BaseDAO):
    """交易数据访问对象"""

    @property
    def table_name(self) -> str:
        return 'trade_order'

    # ========== 账户相关 ==========

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

    def update_account_cash(self, account_id: int, delta: float,
                           operation: str = 'TRADE', conn=None) -> None:
        """
        更新账户现金余额
        :param delta: 变动金额 (正=增加, 负=减少)
        :param operation: 操作类型
        """
        sql = """
        UPDATE sys_account_fund
        SET cash_balance = cash_balance + ?,
            updated_at = datetime('now', 'localtime')
        WHERE account_id = ?
        """
        if conn is not None:
            conn.execute(sql, (delta, account_id))
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, (delta, account_id))

    def update_account_profit(self, account_id: int, pnl: float, conn=None) -> None:
        """更新账户已实现收益"""
        sql = """
        UPDATE sys_account_fund
        SET acc_profit = acc_profit + ?,
            updated_at = datetime('now', 'localtime')
        WHERE account_id = ?
        """
        if conn is not None:
            conn.execute(sql, (pnl, account_id))
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, (pnl, account_id))

    def update_account_flow_totals(
        self,
        account_id: int,
        cash_delta: float,
        deposit_delta: float = 0.0,
        withdraw_delta: float = 0.0,
        conn=None,
    ) -> None:
        """
        更新账户资金缓存摘要。

        说明：
        - 当前阶段仍需维护 sys_account_fund 以兼容现有账户汇总接口。
        - 后续接入统一重算后，这里将只作为结果层刷新入口。
        """
        sql = """
        UPDATE sys_account_fund
        SET cash_balance = cash_balance + ?,
            total_deposit = total_deposit + ?,
            total_withdraw = total_withdraw + ?,
            updated_at = datetime('now', 'localtime')
        WHERE account_id = ?
        """
        params = (cash_delta, deposit_delta, withdraw_delta, account_id)
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, params)

    # ========== 订单相关 ==========

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
            commission, tax, remain_vol, link_order_id, target_rate,
            realized_pnl, status, remark, source_type, source_ref_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (
                order_no, order.account_id, order.asset_code, order.trade_time,
                order.side, order_type, order.price, order.volume, order.amount,
                order.commission, order.tax, order.remain_vol,
                order.link_order_id, order.target_rate, order.realized_pnl,
                order.status, order.remark, order.source_type, order.source_ref_id
            ))
            return cursor.lastrowid
        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, (
                order_no, order.account_id, order.asset_code, order.trade_time,
                order.side, order_type, order.price, order.volume, order.amount,
                order.commission, order.tax, order.remain_vol,
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
            side, order_type, price, volume, amount, commission, tax,
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
            side, order_type, price, volume, amount, commission, tax,
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

    def update_remain_vol(self, order_id: int, remain_vol: float, conn=None) -> None:
        """更新订单剩余份额"""
        sql = "UPDATE trade_order SET remain_vol = ? WHERE order_id = ?"
        if conn is not None:
            conn.execute(sql, (remain_vol, order_id))
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, (remain_vol, order_id))

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
            total_shares = 0,
            broker_name = COALESCE(?, broker_name),
            updated_at = datetime('now', 'localtime')
        WHERE account_id = ?
        """
        params = (
            cash_balance,
            total_deposit,
            total_withdraw,
            acc_profit,
            broker_name,
            account_id,
        )
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, params)

    def update_order_status(self, order_id: int, status: int) -> None:
        """更新订单状态 (1=有效, 0=撤单)"""
        sql = "UPDATE trade_order SET status = ? WHERE order_id = ?"
        with self.db_engine.get_connection() as conn:
            conn.execute(sql, (status, order_id))

    def update_order_details(self, order_id: int, trade_time: str, side: str,
                             price: float, volume: float, amount: float, commission: float, conn=None) -> None:
        """
        更新订单详情 (主要用于数据修正流水)
        注: 不更新 link_order_id、target_rate, realized_pnl 等联动字段, 仅更新本身核心数据
        """
        sql = """
        UPDATE trade_order
        SET trade_time = ?, side = ?, price = ?, volume = ?, amount = ?, commission = ?,
            updated_at = datetime('now', 'localtime')
        WHERE order_id = ?
        """
        if conn is not None:
            conn.execute(sql, (trade_time, side, price, volume, amount, commission, order_id))
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, (trade_time, side, price, volume, amount, commission, order_id))

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

    def insert_audit_log(self, account_id: int, order_id: Optional[int],
                         action_type: str, before_cash: float, after_cash: float,
                         amount_change: float, remark: str = "", conn=None) -> int:
        """插入审计日志"""
        sql = """
        INSERT INTO log_trade_audit (
            account_id, order_id, action_type, before_cash, after_cash,
            amount_change, remark
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (
                account_id, order_id, action_type, before_cash, after_cash,
                amount_change, remark
            ))
            return cursor.lastrowid
        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, (
                account_id, order_id, action_type, before_cash, after_cash,
                amount_change, remark
            ))
            return cursor.lastrowid

    def get_orders(self, account_id: int = 1, page: int = 1, page_size: int = 60) -> List[Dict]:
        """
        分页获取订单记录
        """
        offset = (page - 1) * page_size
        sql = """
        SELECT
            o.order_id, o.order_no, o.account_id, o.asset_code, o.trade_time,
            o.side, o.order_type, o.price, o.volume, o.amount, o.commission, o.tax,
            o.remain_vol, o.link_order_id, o.target_rate, o.realized_pnl,
            o.status, o.remark, o.source_type, o.source_ref_id, o.updated_at, o.created_at,
            m.asset_name
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
            o.side, o.order_type, o.price, o.volume, o.amount, o.commission, o.tax,
            o.remain_vol, o.link_order_id, o.target_rate, o.realized_pnl,
            o.status, o.remark, o.source_type, o.source_ref_id, o.updated_at, o.created_at,
            COALESCE(m.asset_name, o.asset_code) AS asset_name
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
trade_dao = TradeDAO()
