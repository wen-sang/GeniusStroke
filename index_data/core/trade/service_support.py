from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from utils.logger import logger
from utils.validators import ValidationError

from .models import AccountSummary, Lot, Order, Position


class TradeAccountOperations:
    def __init__(self, dao, db_engine, cash_flow_service, account_history_dao, position_dao):
        self.dao = dao
        self.db_engine = db_engine
        self.cash_flow_service = cash_flow_service
        self.account_history_dao = account_history_dao
        self.position_dao = position_dao

    def _normalize_account_name(self, account_name: str) -> str:
        if not isinstance(account_name, str):
            raise ValidationError("账户名称不能为空")
        normalized = account_name.strip()
        if not normalized:
            raise ValidationError("账户名称不能为空")
        if len(normalized) > 50:
            raise ValidationError("账户名称长度不能超过50个字符")
        return normalized

    def _validate_account_name(
        self,
        account_name: str,
        exclude_account_id: Optional[int] = None,
        conn=None,
    ) -> str:
        normalized = self._normalize_account_name(account_name)
        duplicated = self.dao.get_account_by_trimmed_name(normalized, conn=conn)
        if duplicated and duplicated.get("account_id") != exclude_account_id:
            raise ValidationError("账户名称已存在")
        return normalized

    def list_accounts_for_switch(self) -> List[Dict]:
        accounts = self.dao.list_accounts()
        return [
            {
                "account_id": int(item.get("account_id")),
                "account_name": item.get("account_name") or "Default",
            }
            for item in accounts
        ]

    def create_account(self, account_name: str) -> Dict:
        normalized = self._validate_account_name(account_name)
        with self.db_engine.get_connection() as conn:
            account = self.dao.create_account(normalized, conn=conn)
        return {
            "account_id": int(account["account_id"]),
            "account_name": account.get("account_name") or normalized,
        }

    def update_account_name(self, account_id: int, account_name: str) -> Dict:
        account = self.dao.get_account(account_id)
        if not account:
            raise ValidationError("账户不存在")
        normalized = self._validate_account_name(
            account_name,
            exclude_account_id=account_id,
        )
        with self.db_engine.get_connection() as conn:
            self.dao.update_account_name(account_id, normalized, conn=conn)
        return {
            "account_id": int(account_id),
            "account_name": normalized,
        }

    def delete_account(self, account_id: int) -> Dict:
        account = self.dao.get_account(account_id)
        if not account:
            raise ValidationError("账户不存在")
        if self.dao.has_account_asset_data(account_id):
            raise ValidationError("账户已有资产数据，不允许删除")

        with self.db_engine.get_connection() as conn:
            self.dao.delete_account(account_id, conn=conn)
            remaining_account_count = self.dao.count_accounts(conn=conn)
            next_account = (
                self.dao.get_first_account(conn=conn)
                if remaining_account_count > 0
                else None
            )

        return {
            "deleted_account_id": int(account_id),
            "remaining_account_count": int(remaining_account_count),
            "next_account_id": int(next_account["account_id"]) if next_account else None,
        }

    def get_account_summary(self, account_id: int = 1) -> AccountSummary:
        account = self.dao.get_or_create_account(account_id)

        def _get(key, default):
            value = account.get(key)
            return value if value is not None else default

        summary = AccountSummary(
            account_id=account["account_id"],
            account_name=_get("account_name", "Default"),
            broker_name=_get("broker_name", ""),
            cash_balance=_get("cash_balance", 0.0),
            total_deposit=_get("total_deposit", 0.0),
            total_withdraw=_get("total_withdraw", 0.0),
            acc_profit=_get("acc_profit", 0.0),
            commission_rate=_get("commission_rate", 0.00025),
            commission_min=_get("commission_min", 5.0),
            stamp_duty_rate=_get("stamp_duty_rate", 0.001),
        )

        positions = self.position_dao.get_positions_by_account(account_id)
        total_mv = sum(float(p.get("market_value") or 0.0) for p in positions)
        floating_pnl = sum(float(p.get("unrealized_pnl") or 0.0) for p in positions)
        summary.total_market_value = total_mv
        summary.total_asset = summary.cash_balance + total_mv
        summary.floating_pnl = floating_pnl
        summary.history_total_pnl = summary.acc_profit + floating_pnl
        net_investment = summary.total_deposit - summary.total_withdraw
        summary.history_total_pnl_rate = (
            summary.history_total_pnl / net_investment if net_investment > 0 else 0.0
        )

        latest_complete_history = self.account_history_dao.get_latest_complete_history(account_id)
        if latest_complete_history:
            # 汇总页同时展示“当前实时状态”和“最新正式收盘口径”。
            # 其中收益类指标与 data_updated_to 统一来自正式收盘历史，不能读取 live snapshot，
            # 也不能与当前实时状态混用，否则会出现“日期是收盘日，但收益是实时值”的口径冲突。
            summary.daily_return = float(latest_complete_history.get("daily_return") or 0.0)
            summary.daily_return_rate = float(
                latest_complete_history.get("daily_return_rate") or 0.0
            )
            summary.history_total_pnl = float(
                latest_complete_history.get("cum_total_pnl")
                or latest_complete_history.get("total_pnl")
                or summary.history_total_pnl
            )
            summary.history_total_pnl_rate = float(
                latest_complete_history.get("pnl_ratio") or summary.history_total_pnl_rate
            )
            account_xirr = latest_complete_history.get("account_xirr")
            summary.account_xirr = float(account_xirr) if account_xirr is not None else None
            summary.data_updated_to = latest_complete_history.get("trade_date")

        return summary

    def deposit(self, account_id: int, amount: float, remark: str = "") -> None:
        self.cash_flow_service.deposit(
            account_id=account_id,
            amount=amount,
            remark=remark,
        )

    def withdraw(self, account_id: int, amount: float, remark: str = "") -> None:
        self.cash_flow_service.withdraw(
            account_id=account_id,
            amount=amount,
            remark=remark,
        )

    def adjust_cash(self, account_id: int, amount: float, remark: str = "") -> None:
        if amount == 0:
            raise ValidationError("调账金额不能为 0")
        direction = "IN" if amount > 0 else "OUT"
        self.cash_flow_service.adjust(
            account_id=account_id,
            amount=abs(amount),
            direction=direction,
            remark=remark,
        )


class TradeExecutionOperations:
    def __init__(
        self,
        dao,
        db_engine,
        rebuild_service,
        history_rebuild_service,
        mutation_rebuild_orchestrator,
    ):
        self.dao = dao
        self.db_engine = db_engine
        self.rebuild_service = rebuild_service
        self.history_rebuild_service = history_rebuild_service
        self.mutation_rebuild_orchestrator = mutation_rebuild_orchestrator

    @staticmethod
    def _normalize_trade_date(trade_date: str) -> str:
        if not isinstance(trade_date, str):
            raise ValidationError("成交日期不能为空")
        normalized = trade_date.strip()
        if not normalized:
            raise ValidationError("成交日期不能为空")
        try:
            return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValidationError("成交日期格式必须为 YYYY-MM-DD") from exc

    @staticmethod
    def _trade_time_from_date(trade_date: str) -> str:
        return f"{trade_date} 00:00:00"

    @staticmethod
    def _current_biz_date() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _normalize_idempotency_key(idempotency_key: Optional[str]) -> Optional[str]:
        if idempotency_key is None:
            return None
        normalized = str(idempotency_key).strip()
        if not normalized:
            return None
        if len(normalized) > 128:
            raise ValidationError("幂等键长度不能超过128个字符")
        return normalized

    @staticmethod
    def _normalize_fee(value: Optional[float], field_name: str, default: float = 0.0) -> float:
        if value is None:
            return default
        normalized = float(value)
        if normalized < 0:
            raise ValidationError(f"{field_name}不能为负数")
        return normalized

    @staticmethod
    def _is_stock_asset(asset_type: Optional[str]) -> bool:
        return (asset_type or "").upper() == "STOCK"

    def _validate_fee_policy(
        self,
        *,
        asset_type: Optional[str],
        side: str,
        transfer_fee: float,
        tax: float,
    ) -> None:
        is_stock = self._is_stock_asset(asset_type)
        if not is_stock and (transfer_fee > 0 or tax > 0):
            raise ValidationError("非股票交易不允许填写过户费或印花税")
        if side != "SELL" and tax > 0:
            raise ValidationError("只有股票卖出允许填写印花税")

    @staticmethod
    def _fee_summary(commission: float, transfer_fee: float, tax: float) -> str:
        return f"Fee: commission={commission:.2f}, transfer_fee={transfer_fee:.2f}, tax={tax:.2f}"

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
        if price <= 0 or volume <= 0:
            raise ValidationError("价格和数量必须大于 0")
        normalized_trade_date = self._normalize_trade_date(trade_date)
        normalized_idempotency_key = self._normalize_idempotency_key(idempotency_key)

        with self.db_engine.get_connection() as conn:
            if normalized_idempotency_key:
                existing_order = self.dao.get_order_by_manual_source_ref(
                    account_id=account_id,
                    source_ref_id=normalized_idempotency_key,
                    conn=conn,
                )
                if existing_order:
                    return existing_order

            account = self.dao.get_or_create_account(account_id, conn=conn)
            asset_type = self.dao.get_asset_type(asset_code, conn=conn)
            before_cash = account.get("cash_balance", 0.0)
            amount = price * volume

            if commission is None:
                rate = account.get("commission_rate", 0.00025)
                min_comm = account.get("commission_min", 5.0)
                commission = max(amount * rate, min_comm)
            commission = self._normalize_fee(commission, "佣金")
            transfer_fee = self._normalize_fee(transfer_fee, "过户费")
            self._validate_fee_policy(
                asset_type=asset_type,
                side="BUY",
                transfer_fee=transfer_fee,
                tax=0.0,
            )

            total_cost = amount + commission + transfer_fee
            if before_cash < total_cost:
                raise ValidationError(
                    f"可用现金不足: 可用 {before_cash:.2f}, 需要 {total_cost:.2f}"
                )

            after_cash = before_cash - total_cost
            order = Order(
                account_id=account_id,
                asset_code=asset_code,
                trade_time=self._trade_time_from_date(normalized_trade_date),
                side="BUY",
                price=price,
                volume=volume,
                amount=amount,
                commission=commission,
                transfer_fee=transfer_fee,
                remain_vol=volume,
                target_rate=target_rate,
                remark=remark or "BUY",
                source_type="MANUAL",
                source_ref_id=normalized_idempotency_key,
            )

            order_id = self.dao.insert_order(order, conn=conn)
            order.order_id = order_id

            self.dao.insert_audit_log(
                account_id=account_id,
                order_id=order_id,
                action_type="BUY",
                before_cash=before_cash,
                after_cash=after_cash,
                amount_change=-total_cost,
                remark=(
                    f"BUY {asset_code} | Vol:{volume} | Price:{price} | "
                    f"{self._fee_summary(commission, transfer_fee, 0.0)}"
                ),
                conn=conn,
            )
            self.mutation_rebuild_orchestrator.refresh_after_mutation(
                account_id=account_id,
                from_date=normalized_trade_date,
                live_snapshot_date=self._current_biz_date(),
                conn=conn,
            )

        logger.info(
            "[BUY] %s | Vol:%s | Price:%s | Cash: %.2f -> %.2f",
            asset_code,
            volume,
            price,
            before_cash,
            after_cash,
        )
        return order

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
        if price <= 0 or volume <= 0:
            raise ValidationError("价格和数量必须大于 0")
        normalized_trade_date = self._normalize_trade_date(trade_date)
        normalized_idempotency_key = self._normalize_idempotency_key(idempotency_key)

        with self.db_engine.get_connection() as conn:
            if normalized_idempotency_key:
                existing_order = self.dao.get_order_by_manual_source_ref(
                    account_id=account_id,
                    source_ref_id=normalized_idempotency_key,
                    conn=conn,
                )
                if existing_order:
                    return existing_order

            buy_order = self.dao.get_order(link_order_id, conn=conn)
            if not buy_order:
                raise ValidationError(f"买入订单不存在: {link_order_id}")
            if buy_order.account_id != account_id:
                raise ValidationError(
                    f"卖出批次账户不匹配: buy_order.account_id={buy_order.account_id}, current_account_id={account_id}"
                )
            if buy_order.side != "BUY":
                raise ValidationError(f"关联订单不是买入批次: {link_order_id}")
            if buy_order.status != 1:
                raise ValidationError(f"关联买入批次无效: {link_order_id}")
            if buy_order.remain_vol < volume:
                raise ValidationError(
                    f"可用份额不足: 可用 {buy_order.remain_vol}, 卖出 {volume}"
                )

            account = self.dao.get_or_create_account(account_id, conn=conn)
            asset_type = self.dao.get_asset_type(buy_order.asset_code, conn=conn)
            before_cash = account.get("cash_balance", 0.0)
            amount = price * volume

            if commission is None:
                rate = account.get("commission_rate", 0.00025)
                min_comm = account.get("commission_min", 5.0)
                commission = max(amount * rate, min_comm)
            commission = self._normalize_fee(commission, "佣金")
            transfer_fee = self._normalize_fee(transfer_fee, "过户费")

            if tax is None:
                if self._is_stock_asset(asset_type):
                    stamp_rate = account.get("stamp_duty_rate", 0.001)
                    tax = amount * stamp_rate
                else:
                    tax = 0.0
            tax = self._normalize_fee(tax, "印花税")
            self._validate_fee_policy(
                asset_type=asset_type,
                side="SELL",
                transfer_fee=transfer_fee,
                tax=tax,
            )

            net_income = amount - commission - transfer_fee - tax
            buy_amount = buy_order.amount or (buy_order.price * buy_order.volume)
            buy_total_cost = buy_amount + buy_order.commission + buy_order.transfer_fee
            buy_cost_per_share = buy_total_cost / buy_order.volume if buy_order.volume > 0 else 0
            buy_cost = buy_cost_per_share * volume
            realized_pnl = net_income - buy_cost
            after_cash = before_cash + net_income

            order = Order(
                account_id=account_id,
                asset_code=buy_order.asset_code,
                trade_time=self._trade_time_from_date(normalized_trade_date),
                side="SELL",
                price=price,
                volume=volume,
                amount=amount,
                commission=commission,
                transfer_fee=transfer_fee,
                tax=tax,
                link_order_id=link_order_id,
                realized_pnl=realized_pnl,
                remark=remark or "SELL",
                source_type="MANUAL",
                source_ref_id=normalized_idempotency_key,
            )

            order_id = self.dao.insert_order(order, conn=conn)
            order.order_id = order_id

            self.dao.insert_audit_log(
                account_id=account_id,
                order_id=order_id,
                action_type="SELL",
                before_cash=before_cash,
                after_cash=after_cash,
                amount_change=net_income,
                remark=(
                    f"SELL {buy_order.asset_code} | Vol:{volume} | Price:{price} | "
                    f"PnL:{realized_pnl:.2f} | "
                    f"{self._fee_summary(commission, transfer_fee, tax)}"
                ),
                conn=conn,
            )
            self.mutation_rebuild_orchestrator.refresh_after_mutation(
                account_id=account_id,
                from_date=min(normalized_trade_date, buy_order.trade_time[:10]),
                live_snapshot_date=self._current_biz_date(),
                conn=conn,
            )

        logger.info(
            "[SELL] %s | Vol:%s | Price:%s | PnL:%.2f | Cash: %.2f -> %.2f",
            buy_order.asset_code,
            volume,
            price,
            realized_pnl,
            before_cash,
            after_cash,
        )
        return order

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
        if price <= 0 or volume <= 0:
            raise ValidationError("价格和数量必须大于 0")
        if side not in ("BUY", "SELL"):
            raise ValidationError(f"不支持的交易类型: {side}")
        commission = self._normalize_fee(commission, "佣金")
        transfer_fee = self._normalize_fee(transfer_fee, "过户费")

        with self.db_engine.get_connection() as conn:
            order = self.dao.get_order(order_id, conn=conn)
            if not order:
                raise ValidationError(f"需要修改的订单不存在: {order_id}")
            if order.account_id != account_id:
                raise ValidationError("无权修改该账户的订单")

            asset_type = self.dao.get_asset_type(order.asset_code, conn=conn)
            tax_to_write = (
                float(order.tax or 0.0)
                if tax is None and side == "SELL"
                else self._normalize_fee(tax, "印花税", default=0.0)
            )
            self._validate_fee_policy(
                asset_type=asset_type,
                side=side,
                transfer_fee=transfer_fee,
                tax=tax_to_write,
            )

            amount = price * volume
            self.dao.update_order_details(
                order_id=order_id,
                trade_time=trade_time,
                side=side,
                price=price,
                volume=volume,
                amount=amount,
                commission=commission,
                transfer_fee=transfer_fee,
                tax=tax_to_write,
                conn=conn,
            )
            self.dao.insert_audit_log(
                account_id=account_id,
                order_id=order_id,
                action_type="EDIT_ORDER",
                before_cash=0,
                after_cash=0,
                amount_change=0,
                remark=(
                    f"EDIT {order.asset_code} | Old [{order.price}*{order.volume}] -> "
                    f"New [{price}*{volume}] | Remark: {remark}"
                ),
                conn=conn,
            )
            self.mutation_rebuild_orchestrator.refresh_after_mutation(
                account_id=account_id,
                from_date=min(order.trade_time[:10], trade_time[:10]),
                live_snapshot_date=self._current_biz_date(),
                conn=conn,
            )

        logger.info(
            "[EDIT_ORDER] %s | %s | [%s*%s] -> [%s*%s]",
            order_id,
            order.asset_code,
            order.price,
            order.volume,
            price,
            volume,
        )


class TradeQueryOperations:
    def __init__(self, dao, position_dao, quote_cache_dao):
        self.dao = dao
        self.position_dao = position_dao
        self.quote_cache_dao = quote_cache_dao

    def get_positions(
        self,
        account_id: int = 1,
        page: int = 1,
        page_size: int = 60,
    ) -> Dict:
        positions_data = self.dao.get_positions_summary(account_id, page, page_size)
        total_count = self.dao.get_position_count(account_id)
        realized_pnl_map = self.dao.get_realized_pnl_by_asset(account_id)
        position_map = {
            item.get("asset_code"): item
            for item in self.position_dao.get_positions_by_account(account_id)
        }
        quote_cache_map = self.quote_cache_dao.get_quotes_by_codes(list(position_map.keys()))

        positions = []
        for position_data in positions_data:
            cached = position_map.get(position_data.get("asset_code"), {})
            quote_cache = quote_cache_map.get(position_data.get("asset_code"), {})
            position = Position(
                asset_code=position_data.get("asset_code", ""),
                asset_name=position_data.get("asset_name", ""),
                total_volume=position_data.get("total_volume", 0.0),
                avg_cost=position_data.get("avg_cost", 0.0),
                cost_amount=cached.get("cost_amount", 0.0) or 0.0,
                current_price=cached.get("market_price", 0.0) or 0.0,
                market_value=cached.get("market_value", 0.0) or 0.0,
                total_pnl=cached.get("unrealized_pnl", 0.0) or 0.0,
                pnl_rate=cached.get("pnl_ratio", 0.0) or 0.0,
                realized_pnl=realized_pnl_map.get(position_data.get("asset_code", ""), 0.0),
                updated_at=(
                    quote_cache.get("refreshed_at")
                    or quote_cache.get("updated_at")
                    or cached.get("updated_at", "")
                    or ""
                ),
            )
            position.history_total_pnl = position.realized_pnl + position.total_pnl
            positions.append(
                {
                    "asset_code": position.asset_code,
                    "asset_name": position.asset_name,
                    "total_volume": position.total_volume,
                    "avg_cost": position.avg_cost,
                    "cost_amount": position.cost_amount,
                    "current_price": position.current_price,
                    "market_value": position.market_value,
                    "holding_pnl": position.total_pnl,
                    "holding_pnl_rate": position.pnl_rate,
                    "realized_pnl": position.realized_pnl,
                    "history_total_pnl": position.history_total_pnl,
                    "updated_at": position.updated_at,
                }
            )

        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        return {
            "items": positions,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_lots(self, asset_code: str, account_id: int = 1) -> List[Lot]:
        lots_data = self.dao.get_available_lots(asset_code, account_id)
        lots = []
        for lot_data in lots_data:
            buy_price = lot_data.get("buy_price", 0.0)
            target_rate = lot_data.get("target_rate", 0.0)
            lots.append(
                Lot(
                    order_id=lot_data.get("order_id", 0),
                    buy_date=lot_data.get("buy_date", "")[:10],
                    buy_price=buy_price,
                    remain_vol=lot_data.get("remain_vol", 0.0),
                    target_rate=target_rate,
                    target_price=buy_price * (1 + target_rate),
                )
            )
        return lots

    def get_orders(
        self,
        account_id: int = 1,
        page: int = 1,
        page_size: int = 60,
    ) -> Dict:
        orders_data = self.dao.get_orders(account_id, page, page_size)
        total_count = self.dao.get_order_count(account_id)

        orders = []
        for order_data in orders_data:
            Order.from_dict(order_data)
            order_dict = order_data.copy()
            realized_pnl_raw = order_dict.get("realized_pnl")
            realized_return_rate = None
            if (
                order_dict.get("side") == "SELL"
                and int(order_dict.get("status") or 0) == 1
                and order_dict.get("link_order_id")
                and realized_pnl_raw is not None
            ):
                realized_pnl = float(realized_pnl_raw)
                amount = float(order_dict.get("amount") or 0.0)
                commission = float(order_dict.get("commission") or 0.0)
                transfer_fee = float(order_dict.get("transfer_fee") or 0.0)
                tax = float(order_dict.get("tax") or 0.0)
                realized_cost_basis = amount - commission - transfer_fee - tax - realized_pnl
                if realized_cost_basis > 0:
                    realized_return_rate = realized_pnl / realized_cost_basis
            order_dict["realized_return_rate"] = realized_return_rate
            order_dict["realized_pnl"] = order_dict.get("realized_pnl") or 0.0
            order_dict["commission"] = order_dict.get("commission") or 0.0
            order_dict["transfer_fee"] = order_dict.get("transfer_fee") or 0.0
            order_dict["tax"] = order_dict.get("tax") or 0.0
            orders.append(order_dict)

        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        return {
            "items": orders,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
