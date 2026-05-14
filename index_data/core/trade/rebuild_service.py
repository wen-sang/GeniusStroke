"""
账户轻量重算服务

基于 `trade_order + account_cash_flow` 回放当前账户状态，
刷新 `trade_order.remain_vol / realized_pnl`、`dat_position`、`sys_account_fund`。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from core.db_engine import db_engine
from dao.market_dao import market_dao
from dao.position_dao import position_dao
from utils.logger import logger

from dao.trade_dao import trade_dao
from .replay_support import ReplayLotState, ReplayState, trade_replay_support


class AccountRebuildService:
    """当前账户状态轻量重算。"""

    def __init__(self) -> None:
        self.trade_dao = trade_dao
        self.position_dao = position_dao
        self.market_dao = market_dao

    def rebuild_current_state(
        self,
        account_id: int,
        conn=None,
        as_of_date: Optional[str] = None,
        persist: Optional[bool] = None,
    ) -> Dict[str, float]:
        """
        回放账户事实数据。

        规则:
        - 默认刷新“当前状态缓存”
        - 当指定 `as_of_date` 时，默认只做历史口径预览，不覆盖当前缓存
        - 若确实需要按指定日期回写缓存，必须显式传入 `persist=True`
        """
        should_persist = persist if persist is not None else as_of_date is None
        if conn is not None:
            return self._rebuild_with_connection(
                account_id,
                conn,
                as_of_date=as_of_date,
                persist=should_persist,
            )

        with db_engine.get_connection() as write_conn:
            return self._rebuild_with_connection(
                account_id,
                write_conn,
                as_of_date=as_of_date,
                persist=should_persist,
            )

    def preview_current_state(
        self,
        account_id: int,
        conn=None,
        as_of_date: Optional[str] = None,
    ) -> Dict[str, float]:
        """按指定日期预览账户状态，不覆盖当前缓存。"""
        return self.rebuild_current_state(
            account_id=account_id,
            conn=conn,
            as_of_date=as_of_date,
            persist=False,
        )

    def _rebuild_with_connection(
        self,
        account_id: int,
        conn,
        as_of_date: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, float]:
        account = self.trade_dao.get_or_create_account(account_id, conn=conn)
        orders = trade_replay_support.load_orders(account_id=account_id, conn=conn, as_of_date=as_of_date)
        cash_flows = trade_replay_support.load_cash_flows(account_id=account_id, conn=conn, as_of_date=as_of_date)
        corporate_actions = trade_replay_support.load_corporate_actions(
            account_id=account_id,
            conn=conn,
            as_of_date=as_of_date,
        )
        replay_state = ReplayState(account_id=account_id)
        buy_updates: List[tuple] = []
        sell_updates: List[tuple] = []

        events = trade_replay_support.build_replay_events(
            orders=orders,
            cash_flows=cash_flows,
            corporate_actions=corporate_actions,
        )
        for event in events:
            if event["event_kind"] == "corporate_action":
                trade_replay_support.apply_corporate_action(replay_state, event["payload"])
                continue
            if event["event_kind"] == "cash_flow":
                trade_replay_support.apply_cash_flow(replay_state, event["payload"])
                continue

            result = trade_replay_support.apply_order(replay_state, event["payload"])
            if not result or result["side"] != "SELL":
                continue

            sell_updates.append((result["realized_pnl"], result["order_id"]))

        for lot in replay_state.buy_lots.values():
            buy_updates.append((max(lot.remain_vol, 0.0), lot.order_id))

        positions = self._build_positions(
            account_id=account_id,
            buy_lots=replay_state.buy_lots,
            as_of_date=as_of_date,
        )
        if persist:
            self._refresh_order_state(buy_updates=buy_updates, sell_updates=sell_updates, conn=conn)
            self._refresh_positions(account_id=account_id, positions=positions, conn=conn)
            self._refresh_account_summary(
                account_id=account_id,
                cash_balance=replay_state.cash_balance,
                total_deposit=replay_state.total_deposit,
                total_withdraw=replay_state.total_withdraw,
                acc_profit=replay_state.acc_profit,
                broker_name=account.get("broker_name"),
                conn=conn,
            )

        summary = {
            "cash_balance": round(replay_state.cash_balance, 4),
            "total_deposit": round(replay_state.total_deposit, 4),
            "total_withdraw": round(replay_state.total_withdraw, 4),
            "acc_profit": round(replay_state.acc_profit, 4),
            "position_count": float(len(positions)),
            "valuation_date": as_of_date or "",
        }
        logger.debug(
            "[REBUILD_CURRENT] account_id=%s as_of_date=%s persist=%s summary=%s",
            account_id,
            as_of_date,
            persist,
            summary,
        )
        return summary

    def _refresh_order_state(self, buy_updates: List[tuple], sell_updates: List[tuple], conn) -> None:
        self.trade_dao.bulk_update_buy_order_remain_vol(buy_updates, conn=conn)
        self.trade_dao.bulk_update_sell_order_realized_pnl(sell_updates, conn=conn)

    def _build_positions(
        self,
        account_id: int,
        buy_lots: Dict[int, ReplayLotState],
        as_of_date: Optional[str] = None,
    ) -> List[Dict]:
        grouped: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {
                "total_volume": 0.0,
                "available_volume": 0.0,
                "cost_amount": 0.0,
                "target_weighted": 0.0,
            }
        )
        for lot in buy_lots.values():
            if lot.remain_vol <= 1e-8:
                continue
            group = grouped[lot.asset_code]
            group["total_volume"] += lot.remain_vol
            group["available_volume"] += lot.remain_vol
            group["cost_amount"] += lot.remain_vol * lot.unit_cost
            group["target_weighted"] += lot.remain_vol * lot.target_rate

        if as_of_date:
            latest_prices = self.market_dao.get_latest_prices_batch_as_of(list(grouped.keys()), as_of_date)
            fallback_navs = self.market_dao.get_latest_fund_navs_batch_as_of(list(grouped.keys()), as_of_date)
        else:
            latest_prices = self.market_dao.get_latest_prices_batch(list(grouped.keys()))
            latest_trade_date = self.market_dao.get_latest_trade_date_global()
            fallback_navs = (
                self.market_dao.get_latest_fund_navs_batch_as_of(list(grouped.keys()), latest_trade_date)
                if latest_trade_date
                else {}
            )
        positions: List[Dict] = []
        for asset_code, group in grouped.items():
            total_volume = group["total_volume"]
            cost_amount = group["cost_amount"]
            cost_price = cost_amount / total_volume if total_volume > 0 else 0.0
            latest_quote = latest_prices.get(asset_code) or fallback_navs.get(asset_code, {})
            market_price = float(latest_quote.get("close") or 0.0)
            market_value = market_price * total_volume if market_price > 0 else cost_amount
            unrealized_pnl = market_value - cost_amount
            pnl_ratio = unrealized_pnl / cost_amount if cost_amount > 0 else 0.0
            positions.append(
                {
                    "account_id": account_id,
                    "asset_code": asset_code,
                    "total_volume": total_volume,
                    "available_volume": group["available_volume"],
                    "cost_price": cost_price,
                    "cost_amount": cost_amount,
                    "market_price": market_price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized_pnl,
                    "pnl_ratio": pnl_ratio,
                }
            )
        return positions

    def _refresh_positions(self, account_id: int, positions: List[Dict], conn) -> None:
        self.position_dao.replace_account_positions(account_id, positions, conn=conn)

    def _refresh_account_summary(
        self,
        account_id: int,
        cash_balance: float,
        total_deposit: float,
        total_withdraw: float,
        acc_profit: float,
        broker_name: Optional[str],
        conn,
    ) -> None:
        self.trade_dao.refresh_account_summary(
            account_id=account_id,
            cash_balance=cash_balance,
            total_deposit=total_deposit,
            total_withdraw=total_withdraw,
            acc_profit=acc_profit,
            broker_name=broker_name,
            conn=conn,
        )


account_rebuild_service = AccountRebuildService()
