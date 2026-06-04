# core/trade/service.py - 交易业务逻辑层
"""
交易管理服务
v2.4.5: 支持买入、指定批次卖出、撤单
"""
from typing import Dict, List, Optional

from core.db_engine import db_engine
from dao.account_history_dao import account_history_dao
from dao.position_dao import position_dao
from dao.quote_cache_dao import quote_cache_dao

from .cash_flow_service import cash_flow_service
from dao.trade_dao import trade_dao
from .history_rebuild_service import account_history_rebuild_service
from .models import AccountSummary, Lot, Order
from .mutation_rebuild_orchestrator import TradeMutationRebuildOrchestrator
from .rebuild_service import account_rebuild_service
from .service_support import (
    TradeAccountOperations,
    TradeExecutionOperations,
    TradeQueryOperations,
)


class TradeService:
    """交易业务门面服务。"""

    def __init__(self):
        self.dao = trade_dao
        mutation_rebuild_orchestrator = TradeMutationRebuildOrchestrator(
            current_rebuild_service=account_rebuild_service,
            history_rebuild_service=account_history_rebuild_service,
        )
        self._account_ops = TradeAccountOperations(
            dao=self.dao,
            db_engine=db_engine,
            cash_flow_service=cash_flow_service,
            account_history_dao=account_history_dao,
            position_dao=position_dao,
        )
        self._execution_ops = TradeExecutionOperations(
            dao=self.dao,
            db_engine=db_engine,
            rebuild_service=account_rebuild_service,
            history_rebuild_service=account_history_rebuild_service,
            mutation_rebuild_orchestrator=mutation_rebuild_orchestrator,
        )
        self._query_ops = TradeQueryOperations(
            dao=self.dao,
            position_dao=position_dao,
            quote_cache_dao=quote_cache_dao,
        )

    def list_accounts_for_switch(self) -> List[Dict]:
        return self._account_ops.list_accounts_for_switch()

    def create_account(self, account_name: str) -> Dict:
        return self._account_ops.create_account(account_name)

    def update_account_name(self, account_id: int, account_name: str) -> Dict:
        return self._account_ops.update_account_name(account_id, account_name)

    def delete_account(self, account_id: int) -> Dict:
        return self._account_ops.delete_account(account_id)

    def get_account_summary(self, account_id: int = 1) -> AccountSummary:
        return self._account_ops.get_account_summary(account_id)

    def deposit(self, account_id: int, amount: float, remark: str = "") -> None:
        self._account_ops.deposit(account_id, amount, remark)

    def withdraw(self, account_id: int, amount: float, remark: str = "") -> None:
        self._account_ops.withdraw(account_id, amount, remark)

    def adjust_cash(self, account_id: int, amount: float, remark: str = "") -> None:
        self._account_ops.adjust_cash(account_id, amount, remark)

    def buy(
        self,
        account_id: int,
        asset_code: str,
        trade_date: str,
        price: float,
        volume: float,
        target_rate: float = 0.0,
        commission: Optional[float] = None,
        transfer_fee: Optional[float] = 0.0,
        remark: str = "",
        idempotency_key: Optional[str] = None,
    ) -> Order:
        return self._execution_ops.buy(
            account_id=account_id,
            asset_code=asset_code,
            trade_date=trade_date,
            price=price,
            volume=volume,
            target_rate=target_rate,
            commission=commission,
            transfer_fee=transfer_fee,
            remark=remark,
            idempotency_key=idempotency_key,
        )

    def sell(
        self,
        account_id: int,
        link_order_id: int,
        trade_date: str,
        price: float,
        volume: float,
        commission: Optional[float] = None,
        transfer_fee: Optional[float] = 0.0,
        tax: Optional[float] = None,
        remark: str = "",
        idempotency_key: Optional[str] = None,
    ) -> Order:
        return self._execution_ops.sell(
            account_id=account_id,
            link_order_id=link_order_id,
            trade_date=trade_date,
            price=price,
            volume=volume,
            commission=commission,
            transfer_fee=transfer_fee,
            tax=tax,
            remark=remark,
            idempotency_key=idempotency_key,
        )

    def update_order(
        self,
        account_id: int,
        order_id: int,
        trade_time: str,
        side: str,
        price: float,
        volume: float,
        commission: float,
        transfer_fee: float = 0.0,
        tax: Optional[float] = None,
        remark: str = "",
    ) -> None:
        self._execution_ops.update_order(
            account_id=account_id,
            order_id=order_id,
            trade_time=trade_time,
            side=side,
            price=price,
            volume=volume,
            commission=commission,
            transfer_fee=transfer_fee,
            tax=tax,
            remark=remark,
        )

    def get_positions(self, account_id: int = 1, page: int = 1, page_size: int = 60) -> Dict:
        return self._query_ops.get_positions(account_id, page, page_size)

    def get_lots(self, asset_code: str, account_id: int = 1) -> List[Lot]:
        return self._query_ops.get_lots(asset_code, account_id)

    def get_orders(self, account_id: int = 1, page: int = 1, page_size: int = 60) -> Dict:
        return self._query_ops.get_orders(account_id, page, page_size)


trade_service = TradeService()
