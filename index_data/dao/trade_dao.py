# dao/trade_dao.py - 交易数据访问层
"""
交易管理 DAO 门面。

方法实现按职责拆分在 dao/trade/ 各 Mixin 模块：
accounts（账户）、orders（订单）、queries（持仓与绩效查询）。
TradeDAO 类与 trade_dao 单例保持定义于本模块，外部导入路径不变。
"""
from typing import Optional

from dao.base_dao import BaseDAO
from dao.trade.accounts import TradeAccountMixin
from dao.trade.orders import TradeOrderMixin
from dao.trade.queries import TradePositionQueryMixin


class TradeDAO(
    TradeAccountMixin,
    TradeOrderMixin,
    TradePositionQueryMixin,
    BaseDAO,
):
    """交易数据访问对象"""

    @property
    def table_name(self) -> str:
        return 'trade_order'

    # ========== 账户相关 ==========

    def get_asset_type(self, asset_code: str, conn=None) -> Optional[str]:
        """获取资产类型，用于交易费用口径判断。"""
        sql = "SELECT asset_type FROM sys_asset_meta WHERE asset_code = ?"
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else None
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (asset_code,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

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


# 单例导出
trade_dao = TradeDAO()
