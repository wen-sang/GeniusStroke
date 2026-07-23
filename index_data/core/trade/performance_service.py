"""
账户绩效指标服务。

只读取账户、正式历史和绩效口径交易样本，不产生账户或写入数据。
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite, sqrt
from statistics import pstdev
from typing import Dict, List, Optional, Tuple

from core.trade.history_rebuild_calculator import AccountHistoryRebuildCalculator
from dao.account_history_dao import account_history_dao
from dao.cash_flow_dao import cash_flow_dao
from dao.trade_dao import trade_dao
from utils.validators import ValidationError


class AccountPerformanceService:
    """账户绩效指标计算。"""

    # 周期桶内平仓卖单样本低于该值时，胜率/盈亏比不展示（小样本无统计意义）
    MIN_TRADE_QUALITY_SAMPLES = 10

    def get_account_performance(self, account_id: int) -> Dict:
        account = trade_dao.get_account(account_id)
        if not account:
            raise ValidationError("账户不存在")

        history_rows = account_history_dao.get_complete_history(account_id)
        segment_rows = self._current_segment_rows(history_rows)
        segment_start_date = segment_rows[0]["trade_date"] if segment_rows else None
        sell_orders = trade_dao.list_performance_sell_orders(account_id, start_date=segment_start_date)
        total_trade_count = trade_dao.count_performance_trades(account_id, start_date=segment_start_date)
        trade_quality = self._calculate_trade_quality(sell_orders)

        if not segment_rows:
            return {
                "account_id": account_id,
                "data_updated_to": None,
                "net_value": None,
                "cumulative_pnl_existing": None,
                "cumulative_pnl_performance": None,
                "cumulative_twr": None,
                "cumulative_mwr": None,
                "annualized_twr": None,
                "annualized_xirr": None,
                "max_drawdown": None,
                "max_drawdown_start_date": None,
                "max_drawdown_end_date": None,
                "max_drawdown_recovery_date": None,
                "annualized_volatility": None,
                "win_rate": trade_quality["win_rate"],
                "profit_loss_ratio": trade_quality["profit_loss_ratio"],
                "profit_loss_ratio_is_infinite": trade_quality["profit_loss_ratio_is_infinite"],
                "average_win_amount": trade_quality["average_win_amount"],
                "average_loss_amount": trade_quality["average_loss_amount"],
                "total_trade_count": total_trade_count,
                "average_holding_days": trade_quality["average_holding_days"],
                "expectancy": trade_quality["expectancy"],
                "trading_days": 0,
                "calendar_days": 0,
                "data_quality": {
                    "is_complete": False,
                    "messages": ["账户暂无有效正式净值历史"],
                },
            }

        latest = segment_rows[-1]
        trading_days = len(segment_rows)
        calendar_days = self._calendar_days(segment_rows[0]["trade_date"], latest["trade_date"])
        cumulative_twr = self._calculate_cumulative_twr(segment_rows)
        annualized_twr = self._annualize_twr(cumulative_twr, trading_days)
        annualized_xirr = (
            self._to_optional_float(latest.get("account_xirr"))
            if calendar_days >= 180
            else None
        )
        cumulative_mwr = self._calculate_cumulative_mwr(
            self._to_optional_float(latest.get("account_xirr")),
            calendar_days,
        )
        drawdown = self._calculate_max_drawdown(segment_rows)
        annualized_volatility = self._calculate_annualized_volatility(segment_rows)
        existing_pnl = self._to_optional_float(latest.get("cum_realized_pnl"))
        latest_unrealized = self._to_optional_float(latest.get("cum_unrealized_pnl"))
        if existing_pnl is not None and latest_unrealized is not None:
            existing_pnl += latest_unrealized

        return {
            "account_id": account_id,
            "data_updated_to": latest.get("trade_date"),
            "net_value": self._to_optional_float(latest.get("unit_net_value")),
            "cumulative_pnl_existing": existing_pnl,
            "cumulative_pnl_performance": self._to_optional_float(latest.get("cum_total_pnl")),
            "cumulative_twr": cumulative_twr,
            "cumulative_mwr": cumulative_mwr,
            "annualized_twr": annualized_twr,
            "annualized_xirr": annualized_xirr,
            "max_drawdown": drawdown["max_drawdown"],
            "max_drawdown_start_date": drawdown["start_date"],
            "max_drawdown_end_date": drawdown["end_date"],
            "max_drawdown_recovery_date": drawdown["recovery_date"],
            "annualized_volatility": annualized_volatility,
            "win_rate": trade_quality["win_rate"],
            "profit_loss_ratio": trade_quality["profit_loss_ratio"],
            "profit_loss_ratio_is_infinite": trade_quality["profit_loss_ratio_is_infinite"],
            "average_win_amount": trade_quality["average_win_amount"],
            "average_loss_amount": trade_quality["average_loss_amount"],
            "total_trade_count": total_trade_count,
            "average_holding_days": trade_quality["average_holding_days"],
            "expectancy": trade_quality["expectancy"],
            "trading_days": trading_days,
            "calendar_days": calendar_days,
            "data_quality": {
                "is_complete": True,
                "messages": [],
            },
        }

    def get_period_performance(
        self,
        account_id: int,
        granularity: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict:
        """按日/周/月/年/自定义区间分桶的绩效指标（实时聚合，口径与整体绩效一致）。"""
        if granularity not in ("day", "week", "month", "year", "custom"):
            raise ValidationError("granularity 必须是 day/week/month/year/custom")
        if granularity == "custom" and (not start_date or not end_date):
            raise ValidationError("自定义区间必须选择起止日期")
        account = trade_dao.get_account(account_id)
        if not account:
            raise ValidationError("账户不存在")

        history_rows = account_history_dao.get_complete_history(account_id)
        segment_rows = self._current_segment_rows(history_rows)
        segment_start_date = segment_rows[0]["trade_date"] if segment_rows else None
        sell_orders = trade_dao.list_performance_sell_orders(
            account_id, start_date=segment_start_date, end_date=end_date
        )
        cash_flows = cash_flow_dao.list_cash_flows(
            account_id, start_date=segment_start_date, end_date=end_date, limit=100000
        )

        segment_index = {row["trade_date"]: idx for idx, row in enumerate(segment_rows)}
        filtered_rows = [
            row
            for row in segment_rows
            if (not start_date or row["trade_date"] >= start_date)
            and (not end_date or row["trade_date"] <= end_date)
        ]
        if granularity == "custom":
            buckets = [("自定义", filtered_rows)] if filtered_rows else []
        else:
            buckets = self._group_rows_by_period(filtered_rows, granularity)

        items = []
        for label, bucket_rows in buckets:
            first_idx = segment_index[bucket_rows[0]["trade_date"]]
            baseline_row = segment_rows[first_idx - 1] if first_idx > 0 else None
            items.append(
                self._build_period_item(label, bucket_rows, baseline_row, sell_orders, cash_flows)
            )

        return {
            "account_id": account_id,
            "granularity": granularity,
            "start_date": start_date,
            "end_date": end_date,
            "items": items,
        }

    def _group_rows_by_period(self, rows: List[Dict], granularity: str) -> List[Tuple[str, List[Dict]]]:
        """把按交易日升序的历史行分桶为 (period_label, rows) 列表。"""
        buckets: List[Tuple[str, List[Dict]]] = []
        current_label = None
        for row in rows:
            label = self._period_label(row["trade_date"], granularity)
            if label != current_label:
                buckets.append((label, []))
                current_label = label
            buckets[-1][1].append(row)
        return buckets

    def _period_label(self, trade_date: str, granularity: str) -> str:
        if granularity == "day":
            return trade_date
        if granularity == "month":
            return trade_date[:7]
        if granularity == "year":
            return trade_date[:4]
        iso_year, iso_week, _ = datetime.strptime(trade_date, "%Y-%m-%d").date().isocalendar()
        return f"{iso_year}-W{iso_week:02d}"

    def _build_period_item(
        self,
        label: str,
        bucket_rows: List[Dict],
        baseline_row: Optional[Dict],
        sell_orders: List[Dict],
        cash_flows: List[Dict],
    ) -> Dict:
        period_start = bucket_rows[0]["trade_date"]
        period_end = bucket_rows[-1]["trade_date"]
        trade_days = len(bucket_rows)
        calendar_days = self._calendar_days(period_start, period_end)

        cumulative_twr = self._calculate_cumulative_twr(bucket_rows)
        annualized_twr = self._annualize_twr(cumulative_twr, trade_days)
        # 前置桶外最后一行作为回撤起点基准，避免漏算桶首日下跌
        drawdown_rows = ([baseline_row] if baseline_row is not None else []) + bucket_rows
        drawdown = self._calculate_max_drawdown(drawdown_rows)
        annualized_volatility = self._calculate_annualized_volatility(bucket_rows)
        annualized_xirr = (
            self._calculate_period_xirr(bucket_rows, baseline_row, cash_flows)
            if calendar_days >= 180
            else None
        )
        cumulative_mwr = self._calculate_cumulative_mwr(annualized_xirr, calendar_days)

        bucket_sell_orders = [
            order
            for order in sell_orders
            if period_start <= str(order.get("trade_time") or "")[:10] <= period_end
        ]
        trade_quality = self._calculate_trade_quality(bucket_sell_orders)
        if len(bucket_sell_orders) < self.MIN_TRADE_QUALITY_SAMPLES:
            trade_quality["win_rate"] = None
            trade_quality["profit_loss_ratio"] = None
            trade_quality["profit_loss_ratio_is_infinite"] = False

        return {
            "period_label": label,
            "period_start": period_start,
            "period_end": period_end,
            "trade_days": trade_days,
            "period_pnl": self._sum_daily_return(bucket_rows),
            "cumulative_twr": cumulative_twr,
            "cumulative_mwr": cumulative_mwr,
            "annualized_twr": annualized_twr,
            "annualized_xirr": annualized_xirr,
            "max_drawdown": drawdown["max_drawdown"],
            "max_drawdown_start_date": drawdown["start_date"],
            "max_drawdown_end_date": drawdown["end_date"],
            "max_drawdown_recovery_date": drawdown["recovery_date"],
            "annualized_volatility": annualized_volatility,
            "win_rate": trade_quality["win_rate"],
            "profit_loss_ratio": trade_quality["profit_loss_ratio"],
            "profit_loss_ratio_is_infinite": trade_quality["profit_loss_ratio_is_infinite"],
            "average_win_amount": trade_quality["average_win_amount"],
            "average_loss_amount": trade_quality["average_loss_amount"],
            "total_trade_count": len(bucket_sell_orders),
            "average_holding_days": trade_quality["average_holding_days"],
            "expectancy": trade_quality["expectancy"],
            "trading_days": trade_days,
            "calendar_days": calendar_days,
        }

    def _sum_daily_return(self, rows: List[Dict]) -> Optional[float]:
        values = [
            value
            for value in (self._to_optional_float(row.get("daily_return")) for row in rows)
            if value is not None
        ]
        return sum(values) if values else None

    def _calculate_period_xirr(
        self,
        bucket_rows: List[Dict],
        baseline_row: Optional[Dict],
        cash_flows: List[Dict],
    ) -> Optional[float]:
        """周期 XIRR：期初市值（桶外末行 total_asset）作流出，桶内现金流，期末市值作终值。"""
        period_start = bucket_rows[0]["trade_date"]
        period_end = bucket_rows[-1]["trade_date"]
        terminal_value = self._to_optional_float(bucket_rows[-1].get("total_asset"))
        if terminal_value is None:
            return None
        flows: List[Tuple[str, float]] = []
        opening_value = (
            self._to_optional_float(baseline_row.get("total_asset")) if baseline_row else None
        )
        if opening_value:
            flows.append((period_start, -opening_value))
        for flow in cash_flows:
            if flow.get("flow_type") not in ("DEPOSIT", "WITHDRAW", "ADJUST"):
                continue
            biz_date = str(flow.get("biz_date") or "")[:10]
            if not (period_start <= biz_date <= period_end):
                continue
            amount = self._to_optional_float(flow.get("amount")) or 0.0
            signed = amount if flow.get("direction") == "IN" else -amount
            flows.append((biz_date, -signed))
        flows.sort(key=lambda item: item[0])
        return AccountHistoryRebuildCalculator()._calculate_xirr(
            cash_flows=flows,
            valuation_date=period_end,
            terminal_value=terminal_value,
        )

    def _current_segment_rows(self, history_rows: List[Dict]) -> List[Dict]:
        segment: List[Dict] = []
        for row in history_rows:
            total_shares = self._to_optional_float(row.get("total_shares"))
            unit_net_value = self._to_optional_float(row.get("unit_net_value"))
            if total_shares is None or total_shares <= 0 or unit_net_value is None:
                segment = []
                continue
            segment.append(row)
        return segment

    def _calculate_cumulative_twr(self, rows: List[Dict]) -> Optional[float]:
        if not rows:
            return None
        value = 1.0
        has_sample = False
        for row in rows:
            daily_return_rate = self._to_optional_float(row.get("daily_return_rate"))
            if daily_return_rate is None:
                continue
            value *= 1.0 + daily_return_rate
            has_sample = True
        return value - 1.0 if has_sample else None

    def _annualize_twr(self, cumulative_twr: Optional[float], trading_days: int) -> Optional[float]:
        if cumulative_twr is None or trading_days < 126:
            return None
        return (1.0 + cumulative_twr) ** (252.0 / trading_days) - 1.0

    def _calculate_cumulative_mwr(self, annualized_xirr: Optional[float], calendar_days: int) -> Optional[float]:
        if annualized_xirr is None or calendar_days <= 0:
            return None
        return (1.0 + annualized_xirr) ** (calendar_days / 365.0) - 1.0

    def _calculate_max_drawdown(self, rows: List[Dict]) -> Dict[str, Optional[float | str]]:
        peak_value = None
        peak_date = None
        max_drawdown = 0.0
        start_date = None
        end_date = None
        recovery_date = None

        for row in rows:
            unit_net_value = self._to_optional_float(row.get("unit_net_value"))
            if unit_net_value is None:
                continue
            trade_date = row.get("trade_date")
            if peak_value is None or unit_net_value > peak_value:
                if end_date and recovery_date is None and unit_net_value >= peak_value:
                    recovery_date = trade_date
                peak_value = unit_net_value
                peak_date = trade_date
                continue
            if peak_value <= 0:
                continue
            drawdown = peak_value and (peak_value - unit_net_value) / peak_value
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                start_date = peak_date
                end_date = trade_date
                recovery_date = None

        return {
            "max_drawdown": max_drawdown if max_drawdown > 0 else None,
            "start_date": start_date,
            "end_date": end_date,
            "recovery_date": recovery_date,
        }

    def _calculate_annualized_volatility(self, rows: List[Dict]) -> Optional[float]:
        returns = [
            value
            for value in (self._to_optional_float(row.get("daily_return_rate")) for row in rows)
            if value is not None
        ]
        if len(returns) < 20:
            return None
        return pstdev(returns) * sqrt(252.0)

    def _calculate_trade_quality(self, sell_orders: List[Dict]) -> Dict:
        realized_values = [
            self._to_optional_float(order.get("realized_pnl"))
            for order in sell_orders
        ]
        realized_values = [value for value in realized_values if value is not None]
        if not realized_values:
            return {
                "win_rate": None,
                "profit_loss_ratio": None,
                "profit_loss_ratio_is_infinite": False,
                "average_win_amount": None,
                "average_loss_amount": None,
                "average_holding_days": self._calculate_average_holding_days(sell_orders),
                "expectancy": None,
            }

        wins = [value for value in realized_values if value > 0]
        losses = [abs(value) for value in realized_values if value < 0]
        win_rate = len(wins) / len(realized_values)
        expectancy = sum(realized_values) / len(realized_values)
        average_win_amount = sum(wins) / len(wins) if wins else None
        average_loss_amount = sum(losses) / len(losses) if losses else None
        if not wins:
            profit_loss_ratio = 0.0
            is_infinite = False
        elif not losses:
            profit_loss_ratio = None
            is_infinite = True
        else:
            profit_loss_ratio = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
            is_infinite = False

        return {
            "win_rate": win_rate,
            "profit_loss_ratio": profit_loss_ratio,
            "profit_loss_ratio_is_infinite": is_infinite,
            "average_win_amount": average_win_amount,
            "average_loss_amount": average_loss_amount,
            "average_holding_days": self._calculate_average_holding_days(sell_orders),
            "expectancy": expectancy,
        }

    def _calculate_average_holding_days(self, sell_orders: List[Dict]) -> Optional[float]:
        holding_days = []
        for order in sell_orders:
            sell_date = self._parse_order_date(order.get("trade_time"))
            buy_date = self._parse_order_date(order.get("buy_trade_time"))
            if sell_date is None or buy_date is None:
                continue
            holding_days.append(max((sell_date - buy_date).days, 0))
        return sum(holding_days) / len(holding_days) if holding_days else None

    def _parse_order_date(self, value) -> Optional[datetime]:
        if not value:
            return None
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")

    def _calendar_days(self, start_date: str, end_date: str) -> int:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        return max((end - start).days + 1, 0)

    def _to_optional_float(self, value) -> Optional[float]:
        if value is None:
            return None
        number = float(value)
        return number if isfinite(number) else None


account_performance_service = AccountPerformanceService()
