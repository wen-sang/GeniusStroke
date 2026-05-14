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
        xirr_cash_flows: List[Tuple[str, float]] = []

        for trade_date in trade_dates:
            day_actions = corporate_action_map.get(trade_date, [])
            split_factor_map = self._build_split_factor_map(day_actions)
            for action in day_actions:
                trade_replay_support.apply_corporate_action(replay_state, action)
            for flow in cash_flow_map.get(trade_date, []):
                signed_amount = trade_replay_support.apply_cash_flow(replay_state, flow)
                xirr_cash_flows.append((trade_date, -signed_amount))

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
            cum_total_pnl = replay_state.acc_profit + cum_unrealized_pnl
            net_investment = replay_state.total_deposit - replay_state.total_withdraw
            pnl_ratio = cum_total_pnl / net_investment if net_investment > 0 else 0.0

            if previous_trade_date is None:
                daily_return = 0.0
                daily_return_rate = 0.0
            else:
                daily_return, daily_return_base, day_missing_quotes = (
                    self._calculate_closing_holding_daily_metrics(
                        lots=replay_state.buy_lots.values(),
                        valuation_date=trade_date,
                        current_price_map=current_price_map,
                        previous_price_map=previous_price_map,
                        split_factor_map=split_factor_map,
                    )
                )
                if day_missing_quotes:
                    missing_quotes.extend(day_missing_quotes)
                    break
                daily_return_rate = (
                    daily_return / daily_return_base if daily_return_base > 0 else 0.0
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
                        "total_shares": 0.0,
                        "unit_net_value": 0.0,
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

        return self._match_legacy_price_fallback(asset_code, trade_date)

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
    ) -> float:
        if terminal_value <= 0:
            return 0.0
        flows = cash_flows + [(valuation_date, terminal_value)]
        if len(flows) < 2:
            return 0.0

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

        def derivative(rate: float) -> float:
            total = 0.0
            for years, amount in dated_flows:
                if years == 0:
                    continue
                total -= years * amount / ((1.0 + rate) ** (years + 1.0))
            return total

        rate = 0.1
        for _ in range(50):
            f_value = npv(rate)
            d_value = derivative(rate)
            if abs(d_value) < 1e-12:
                break
            next_rate = rate - f_value / d_value
            if not isfinite(next_rate) or next_rate <= -0.999999:
                break
            if abs(next_rate - rate) < 1e-7:
                return next_rate
            rate = next_rate

        return 0.0


account_history_rebuild_calculator = AccountHistoryRebuildCalculator()
