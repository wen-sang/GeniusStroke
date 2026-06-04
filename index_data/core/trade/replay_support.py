"""
交易事实回放共享助手。

为当前状态重算与历史重算提供统一的：
- 订单/资金流水加载
- 回放事件排序
- 资金与买入批次状态更新
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from utils.validators import ValidationError


@dataclass
class ReplayLotState:
    order_id: int
    account_id: int
    asset_code: str
    open_date: str
    volume: float
    remain_vol: float
    unit_cost: float
    buy_price: float = 0.0  # 不含佣金的原始成交价，用于当日收益计算
    target_rate: float = 0.0


@dataclass
class ReplayState:
    account_id: int
    cash_balance: float = 0.0
    total_deposit: float = 0.0
    total_withdraw: float = 0.0
    acc_profit: float = 0.0
    buy_lots: Optional[Dict[int, ReplayLotState]] = None

    def __post_init__(self) -> None:
        if self.buy_lots is None:
            self.buy_lots = {}


class TradeReplaySupport:
    @staticmethod
    def _get_table_columns(conn, table_name: str) -> set[str]:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        return {row[1] for row in cursor.fetchall()}

    def load_orders(self, account_id: int, conn, as_of_date: Optional[str] = None) -> List[Dict]:
        cursor = conn.cursor()
        columns = self._get_table_columns(conn, "trade_order")
        order_type_expr = "order_type" if "order_type" in columns else "'' AS order_type"
        transfer_fee_expr = "transfer_fee" if "transfer_fee" in columns else "0 AS transfer_fee"
        sql = f"""
            SELECT
                order_id, account_id, asset_code, trade_time, side, {order_type_expr}, price, volume, amount,
                commission, {transfer_fee_expr}, tax, remain_vol, link_order_id, target_rate, realized_pnl,
                status, remark, source_type, source_ref_id, updated_at, created_at
            FROM trade_order
            WHERE account_id = ? AND status = 1
        """
        params = [account_id]
        if as_of_date:
            sql += " AND substr(trade_time, 1, 10) <= ?"
            params.append(as_of_date)
        sql += """
            ORDER BY trade_time ASC, order_id ASC
        """
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def load_cash_flows(self, account_id: int, conn, as_of_date: Optional[str] = None) -> List[Dict]:
        cursor = conn.cursor()
        columns = self._get_table_columns(conn, "account_cash_flow")
        status_expr = "status" if "status" in columns else "'ACTIVE' AS status"
        status_filter = "AND COALESCE(status, 'ACTIVE') = 'ACTIVE'" if "status" in columns else ""
        sql = f"""
            SELECT
                flow_id, account_id, biz_date, flow_type, direction, amount, {status_expr}, remark,
                source_type, source_ref_id, created_at, updated_at
            FROM account_cash_flow
            WHERE account_id = ?
              {status_filter}
        """
        params = [account_id]
        if as_of_date:
            sql += " AND biz_date <= ?"
            params.append(as_of_date)
        sql += """
            ORDER BY biz_date ASC, flow_id ASC
        """
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def load_corporate_actions(self, account_id: int, conn, as_of_date: Optional[str] = None) -> List[Dict]:
        if not self._get_table_columns(conn, "account_corporate_action"):
            return []
        cursor = conn.cursor()
        sql = """
            SELECT
                action_id, account_id, asset_code, action_type, effective_date, record_date,
                cash_base_unit, cash_amount, ratio_from, ratio_to, reinvest_price,
                rounding_policy, status, remark, source_type, source_ref_id,
                confirmed_at, last_check_at, last_error_message, created_at, updated_at
            FROM account_corporate_action
            WHERE account_id = ? AND status = 'CONFIRMED'
        """
        params = [account_id]
        if as_of_date:
            sql += " AND effective_date <= ?"
            params.append(as_of_date)
        sql += """
            ORDER BY effective_date ASC, action_id ASC
        """
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def build_replay_events(
        self,
        orders: List[Dict],
        cash_flows: List[Dict],
        corporate_actions: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        events: List[Dict] = []
        for action in corporate_actions or []:
            events.append(
                {
                    "event_time": f"{action['effective_date']} 00:00:00",
                    "priority": self._action_priority(action),
                    "sequence": int(action["action_id"]),
                    "event_kind": "corporate_action",
                    "payload": action,
                }
            )
        for cash_flow in cash_flows:
            events.append(
                {
                    "event_time": f"{cash_flow['biz_date']} 00:00:00",
                    "priority": 0,
                    "sequence": int(cash_flow["flow_id"]),
                    "event_kind": "cash_flow",
                    "payload": cash_flow,
                }
            )
        for order in orders:
            events.append(
                {
                    "event_time": order["trade_time"],
                    "priority": self._order_priority(order),
                    "sequence": int(order["order_id"]),
                    "event_kind": "order",
                    "payload": order,
                }
            )
        events.sort(key=lambda item: (item["event_time"], item["priority"], item["sequence"]))
        return events

    def group_cash_flows_by_date(self, cash_flows: List[Dict]) -> Dict[str, List[Dict]]:
        grouped: Dict[str, List[Dict]] = {}
        for flow in cash_flows:
            grouped.setdefault(flow["biz_date"], []).append(flow)
        return grouped

    def group_corporate_actions_by_date(self, corporate_actions: List[Dict]) -> Dict[str, List[Dict]]:
        grouped: Dict[str, List[Dict]] = {}
        for action in corporate_actions:
            grouped.setdefault(action["effective_date"], []).append(action)
        for actions in grouped.values():
            actions.sort(key=lambda item: (self._action_priority(item), int(item["action_id"])))
        return grouped

    def group_orders_by_date(self, orders: List[Dict]) -> Dict[str, List[Dict]]:
        grouped: Dict[str, List[Dict]] = {}
        for order in orders:
            grouped.setdefault(order["trade_time"][:10], []).append(order)
        for day_orders in grouped.values():
            day_orders.sort(
                key=lambda item: (
                    self._order_priority(item),
                    item["trade_time"],
                    int(item["order_id"]),
                )
            )
        return grouped

    def resolve_start_date(
        self,
        orders: List[Dict],
        cash_flows: List[Dict],
        corporate_actions: Optional[List[Dict]] = None,
    ) -> Optional[str]:
        dates: List[str] = []
        dates.extend(order["trade_time"][:10] for order in orders if order.get("trade_time"))
        dates.extend(flow["biz_date"] for flow in cash_flows if flow.get("biz_date"))
        dates.extend(
            action["effective_date"]
            for action in (corporate_actions or [])
            if action.get("effective_date")
        )
        return min(dates) if dates else None

    def apply_cash_flow(self, state: ReplayState, cash_flow: Dict) -> float:
        direction = (cash_flow.get("direction") or "IN").upper()
        amount = float(cash_flow.get("amount") or 0.0)
        if direction == "IN":
            signed_amount = amount
            state.cash_balance += amount
        elif direction == "OUT":
            signed_amount = -amount
            state.cash_balance -= amount
        else:
            raise ValidationError(f"非法资金流水方向: {direction}")

        flow_type = (cash_flow.get("flow_type") or "").upper()
        if flow_type == "DEPOSIT":
            state.total_deposit += amount
        elif flow_type == "WITHDRAW":
            state.total_withdraw += amount
        return signed_amount

    def apply_order(self, state: ReplayState, order: Dict) -> Optional[Dict]:
        side = (order.get("side") or "").upper()
        order_type = (order.get("order_type") or "").upper()
        order_id = int(order["order_id"])
        amount = float(order.get("amount") or 0.0)
        commission = float(order.get("commission") or 0.0)
        transfer_fee = float(order.get("transfer_fee") or 0.0)
        tax = float(order.get("tax") or 0.0)
        volume = float(order.get("volume") or 0.0)

        if order_type == "SPLIT_ADJUST":
            return {
                "side": side,
                "order_type": order_type,
                "order_id": order_id,
                "volume": volume,
                "amount": amount,
            }

        if side == "BUY":
            total_cost = amount + commission + transfer_fee
            state.cash_balance -= total_cost
            if state.cash_balance < -1e-6:
                raise ValidationError(
                    f"账户 {state.account_id} 在买入订单 {order_id} 后现金为负: {state.cash_balance:.2f}"
                )
            unit_cost = total_cost / volume if volume > 0 else 0.0
            state.buy_lots[order_id] = ReplayLotState(
                order_id=order_id,
                account_id=state.account_id,
                asset_code=order["asset_code"],
                open_date=order["trade_time"][:10],
                volume=volume,
                remain_vol=volume,
                unit_cost=unit_cost,
                buy_price=float(order.get("price") or 0.0),
                target_rate=float(order.get("target_rate") or 0.0),
            )
            return {
                "side": side,
                "order_id": order_id,
                "volume": volume,
                "amount": amount,
                "commission": commission,
                "transfer_fee": transfer_fee,
                "tax": tax,
            }

        if side != "SELL":
            return {
                "side": side,
                "order_id": order_id,
                "volume": volume,
                "amount": amount,
                "commission": commission,
                "transfer_fee": transfer_fee,
                "tax": tax,
            }

        link_order_id = order.get("link_order_id")
        if not link_order_id or int(link_order_id) not in state.buy_lots:
            raise ValidationError(f"卖单 {order_id} 关联买单无效: {link_order_id}")

        linked_buy = state.buy_lots[int(link_order_id)]
        if linked_buy.asset_code != order["asset_code"]:
            raise ValidationError(
                f"卖单 {order_id} 与买单 {link_order_id} 标的不一致: "
                f"{order['asset_code']} != {linked_buy.asset_code}"
            )
        if linked_buy.remain_vol + 1e-8 < volume:
            raise ValidationError(
                f"卖单 {order_id} 超卖: 剩余 {linked_buy.remain_vol}, 卖出 {volume}"
            )

        linked_buy.remain_vol -= volume
        net_income = amount - commission - transfer_fee - tax
        realized_pnl = net_income - linked_buy.unit_cost * volume
        state.cash_balance += net_income
        state.acc_profit += realized_pnl
        return {
            "side": side,
            "order_id": order_id,
            "link_order_id": int(link_order_id),
            "linked_buy": linked_buy,
            "volume": volume,
            "amount": amount,
            "commission": commission,
            "transfer_fee": transfer_fee,
            "tax": tax,
            "net_income": net_income,
            "realized_pnl": realized_pnl,
        }

    def apply_corporate_action(self, state: ReplayState, action: Dict) -> Optional[Dict]:
        action_type = (action.get("action_type") or "").upper()
        if action_type != "SPLIT":
            return {"action_type": action_type, "action_id": int(action["action_id"])}

        ratio_from = int(action.get("ratio_from") or 0)
        ratio_to = int(action.get("ratio_to") or 0)
        if ratio_from <= 0 or ratio_to <= 0:
            raise ValidationError(f"非法拆分比例: {ratio_from}:{ratio_to}")

        affected_lots = 0
        asset_code = action.get("asset_code")
        for lot in state.buy_lots.values():
            if lot.asset_code != asset_code or lot.remain_vol <= 0:
                continue
            lot.volume = lot.volume * ratio_to / ratio_from
            lot.remain_vol = lot.remain_vol * ratio_to / ratio_from
            lot.unit_cost = lot.unit_cost * ratio_from / ratio_to
            affected_lots += 1
        return {
            "action_type": action_type,
            "action_id": int(action["action_id"]),
            "affected_lots": affected_lots,
        }

    def _action_priority(self, action: Dict) -> int:
        action_type = (action.get("action_type") or "").upper()
        if action_type == "SPLIT":
            return -1
        return 0

    def _order_priority(self, order: Dict) -> int:
        order_type = (order.get("order_type") or "").upper()
        if order_type == "SPLIT_ADJUST":
            return 1
        source_type = (order.get("source_type") or "").upper()
        if source_type == "CORPORATE_ACTION":
            return 1
        return 2


trade_replay_support = TradeReplaySupport()
