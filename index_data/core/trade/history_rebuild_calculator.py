"""
账户历史重算纯计算逻辑。

该模块不访问数据库，只根据已加载的业务事实、交易日和行情 map 生成
`dat_account_history` 写入行。
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Dict, List, Optional, Tuple

from .replay_support import ReplayState, trade_replay_support


class AccountHistoryRebuildCalculator:
    """账户历史收益重算计算器。"""

    # 保留已确认的 159100 历史人工补丁，直到业务明确要求退役。
    LEGACY_PRICE_FALLBACKS = {
        ("159100", "2025-10-31"): 1.0,
    }
    LEGACY_PRICE_FALLBACK_RANGES = [
        {
            "asset_code": "159100",
            "start_date": "2025-10-31",
            "end_date": "2025-11-14",
            "close": 1.0,
        },
    ]

    def build_history_rows(
        self,
        account_id: int,
        trade_dates: List[str],
        emit_from_date: str,
        cash_flow_map: Dict[str, List[Dict]],
        corporate_action_map: Dict[str, List[Dict]],
        order_map: Dict[str, List[Dict]],
        price_map: Dict[Tuple[str, str], float],
        fund_nav_map: Dict[Tuple[str, str], float],
    ) -> Tuple[List[Dict], List[Dict]]:
        replay_state = ReplayState(account_id=account_id)
        history_rows: List[Dict] = []
        missing_quotes: List[Dict] = []
        previous_trade_date: Optional[str] = None
        previous_total_asset = 0.0
        total_shares = 0.0
        current_segment_net_external_investment = 0.0
        previous_effective_unit_net_value: Optional[float] = None
        xirr_cash_flows: List[Tuple[str, float]] = []
        cash_flows = sorted(
            [flow for flows in cash_flow_map.values() for flow in flows],
            key=lambda item: (item.get("biz_date") or "", int(item.get("flow_id") or 0)),
        )
        cash_flow_index = 0

        for trade_date in trade_dates:
            day_actions = corporate_action_map.get(trade_date, [])
            split_factor_map = self._build_split_factor_map(day_actions)
            for action in day_actions:
                trade_replay_support.apply_corporate_action(replay_state, action)

            day_external_cash = 0.0
            day_start_unit_net_value = previous_effective_unit_net_value or 1.0
            while cash_flow_index < len(cash_flows):
                flow = cash_flows[cash_flow_index]
                if (flow.get("biz_date") or "") > trade_date:
                    break
                signed_amount = trade_replay_support.apply_cash_flow(replay_state, flow)
                if self._is_external_cash_flow(flow):
                    if total_shares <= 1e-8 and signed_amount > 0:
                        total_shares = 0.0
                        current_segment_net_external_investment = 0.0
                        xirr_cash_flows = []
                        day_start_unit_net_value = 1.0
                    if day_start_unit_net_value > 0:
                        total_shares += signed_amount / day_start_unit_net_value
                    current_segment_net_external_investment += signed_amount
                    day_external_cash += signed_amount
                    xirr_cash_flows.append((flow["biz_date"], -signed_amount))
                    if total_shares <= 1e-8:
                        total_shares = 0.0
                        current_segment_net_external_investment = 0.0
                        previous_effective_unit_net_value = None
                        xirr_cash_flows = []
                cash_flow_index += 1

            for order in order_map.get(trade_date, []):
                result = trade_replay_support.apply_order(replay_state, order)
                if not result or result["side"] != "SELL":
                    continue

            market_value = 0.0
            remain_cost = 0.0
            current_price_map: Dict[str, float] = {}
            previous_price_map: Dict[str, float] = {}
            for lot in replay_state.buy_lots.values():
                if lot.remain_vol <= 1e-8:
                    continue
                close_price = self._resolve_close_price(
                    asset_code=lot.asset_code,
                    trade_date=trade_date,
                    price_map=price_map,
                    fund_nav_map=fund_nav_map,
                )
                if close_price is None:
                    missing_quotes.append({"asset_code": lot.asset_code, "trade_date": trade_date})
                    continue
                current_price_map[lot.asset_code] = close_price
                if previous_trade_date is not None and lot.open_date != trade_date:
                    previous_price = previous_price_map.get(lot.asset_code)
                    if previous_price is None:
                        previous_price = self._resolve_close_price(
                            asset_code=lot.asset_code,
                            trade_date=previous_trade_date,
                            price_map=price_map,
                            fund_nav_map=fund_nav_map,
                        )
                        if previous_price is None:
                            missing_quotes.append(
                                {"asset_code": lot.asset_code, "trade_date": trade_date}
                            )
                            continue
                        previous_price_map[lot.asset_code] = previous_price
                market_value += lot.remain_vol * close_price
                remain_cost += lot.remain_vol * lot.unit_cost

            if missing_quotes:
                break

            total_asset = replay_state.cash_balance + market_value
            cum_unrealized_pnl = market_value - remain_cost
            unit_net_value = total_asset / total_shares if total_shares > 1e-8 else None
            net_investment = current_segment_net_external_investment
            cum_total_pnl = (
                total_asset - current_segment_net_external_investment
                if unit_net_value is not None
                else None
            )
            pnl_ratio = (
                cum_total_pnl / net_investment
                if cum_total_pnl is not None and net_investment > 0
                else None
            )
            daily_return = total_asset - previous_total_asset - day_external_cash
            daily_return_rate = (
                unit_net_value / day_start_unit_net_value - 1.0
                if unit_net_value is not None and day_start_unit_net_value > 0
                else None
            )

            account_xirr = self._calculate_xirr(
                cash_flows=xirr_cash_flows,
                valuation_date=trade_date,
                terminal_value=total_asset,
            )
            if trade_date >= emit_from_date:
                history_rows.append(
                    {
                        "account_id": account_id,
                        "trade_date": trade_date,
                        "cash_balance": replay_state.cash_balance,
                        "market_value": market_value,
                        "total_asset": total_asset,
                        "total_deposit": replay_state.total_deposit,
                        "total_withdraw": replay_state.total_withdraw,
                        "total_shares": total_shares,
                        "unit_net_value": unit_net_value,
                        "daily_return": daily_return,
                        "daily_return_rate": daily_return_rate,
                        "net_investment": net_investment,
                        "total_pnl": cum_total_pnl,
                        "pnl_ratio": pnl_ratio,
                        "cum_realized_pnl": replay_state.acc_profit,
                        "cum_unrealized_pnl": cum_unrealized_pnl,
                        "cum_total_pnl": cum_total_pnl,
                        "account_xirr": account_xirr,
                        "is_data_complete": 1,
                    }
                )
            if unit_net_value is not None:
                previous_effective_unit_net_value = unit_net_value
            previous_total_asset = total_asset
            previous_trade_date = trade_date

        dedup_missing = []
        seen = set()
        for item in missing_quotes:
            key = (item["asset_code"], item["trade_date"])
            if key not in seen:
                seen.add(key)
                dedup_missing.append(item)
        return history_rows, dedup_missing

    def _build_split_factor_map(self, corporate_actions: List[Dict]) -> Dict[str, float]:
        factors: Dict[str, float] = {}
        for action in corporate_actions:
            if (action.get("action_type") or "").upper() != "SPLIT":
                continue
            asset_code = action.get("asset_code")
            ratio_from = int(action.get("ratio_from") or 0)
            ratio_to = int(action.get("ratio_to") or 0)
            if not asset_code or ratio_from <= 0 or ratio_to <= 0:
                continue
            factors[asset_code] = factors.get(asset_code, 1.0) * (ratio_from / ratio_to)
        return factors

    def _calculate_closing_holding_daily_metrics(
        self,
        lots,
        valuation_date: str,
        current_price_map: Dict[str, float],
        previous_price_map: Dict[str, float],
        split_factor_map: Dict[str, float],
    ) -> Tuple[float, float, List[Dict]]:
        daily_return = 0.0
        daily_return_base = 0.0
        missing_quotes: List[Dict] = []

        for lot in lots:
            if lot.remain_vol <= 1e-8:
                continue

            current_price = current_price_map.get(lot.asset_code)
            if current_price is None:
                missing_quotes.append({"asset_code": lot.asset_code, "trade_date": valuation_date})
                continue

            if lot.open_date == valuation_date:
                reference_price = lot.buy_price
            else:
                previous_price = previous_price_map.get(lot.asset_code)
                if previous_price is None:
                    missing_quotes.append({"asset_code": lot.asset_code, "trade_date": valuation_date})
                    continue
                reference_price = previous_price * split_factor_map.get(lot.asset_code, 1.0)

            reference_value = lot.remain_vol * reference_price
            daily_return += lot.remain_vol * (current_price - reference_price)
            daily_return_base += reference_value

        return daily_return, daily_return_base, missing_quotes

    def _is_external_cash_flow(self, cash_flow: Dict) -> bool:
        flow_type = (cash_flow.get("flow_type") or "").upper()
        return flow_type in {"DEPOSIT", "WITHDRAW", "ADJUST"}

    def _resolve_close_price(
        self,
        asset_code: str,
        trade_date: str,
        price_map: Dict[Tuple[str, str], float],
        fund_nav_map: Dict[Tuple[str, str], float],
    ) -> Optional[float]:
        quote_key = (asset_code, trade_date)
        close_price = price_map.get(quote_key)
        if close_price is not None:
            return close_price

        close_price = fund_nav_map.get(quote_key)
        if close_price is not None:
            return close_price

        fallback_price = self._match_legacy_price_fallback(asset_code, trade_date)
        if fallback_price is not None:
            return fallback_price

        dated_prices = [
            (date, float(price))
            for (code, date), price in {**fund_nav_map, **price_map}.items()
            if code == asset_code and date <= trade_date and price is not None
        ]
        if dated_prices:
            return max(dated_prices, key=lambda item: item[0])[1]
        return None

    def _match_legacy_price_fallback(self, asset_code: str, trade_date: str) -> Optional[float]:
        """匹配保留中的历史人工价格补丁。"""
        quote_key = (asset_code, trade_date)
        point_fallback = self.LEGACY_PRICE_FALLBACKS.get(quote_key)
        if point_fallback is not None:
            return float(point_fallback)

        for rule in self.LEGACY_PRICE_FALLBACK_RANGES:
            if rule["asset_code"] != asset_code:
                continue
            if rule["start_date"] <= trade_date <= rule["end_date"]:
                return float(rule["close"])
        return None

    def _calculate_xirr(
        self,
        cash_flows: List[Tuple[str, float]],
        valuation_date: str,
        terminal_value: float,
    ) -> Optional[float]:
        if terminal_value <= 0:
            return None
        flows = cash_flows + [(valuation_date, terminal_value)]
        if len(flows) < 2:
            return None
        if not any(amount < 0 for _, amount in flows) or not any(amount > 0 for _, amount in flows):
            return None

        base_date = datetime.strptime(flows[0][0], "%Y-%m-%d")
        dated_flows = [
            ((datetime.strptime(date_str, "%Y-%m-%d") - base_date).days / 365.0, amount)
            for date_str, amount in flows
        ]

        def npv(rate: float) -> float:
            total = 0.0
            for years, amount in dated_flows:
                total += amount / ((1.0 + rate) ** years)
            return total

        low = -0.999999
        high = 1.0
        low_value = npv(low)
        high_value = npv(high)
        for _ in range(40):
            if isfinite(low_value) and isfinite(high_value) and low_value * high_value <= 0:
                break
            high *= 2.0
            if high > 1_000_000:
                return None
            high_value = npv(high)
        else:
            return None

        for _ in range(200):
            candidate = (low + high) / 2.0
            value = npv(candidate)
            if not isfinite(value):
                return None
            if abs(value) < 1e-7 or abs(high - low) < 1e-7:
                return candidate
            if low_value * value <= 0:
                high = candidate
                high_value = value
            else:
                low = candidate
                low_value = value
        return None


account_history_rebuild_calculator = AccountHistoryRebuildCalculator()
