"""
账户历史重算服务

按交易日回放账户现金、持仓与收盘价，生成 `dat_account_history`。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from core.db_engine import db_engine
from dao.account_history_dao import account_history_dao
from dao.cash_flow_dao import cash_flow_dao
from dao.market_dao import market_dao
from dao.position_dao import position_dao
from dao.trade_dao import trade_dao
from utils.logger import logger
from utils.validators import ValidationError
from .history_rebuild_calculator import account_history_rebuild_calculator
from .replay_support import trade_replay_support


class AccountHistoryRebuildService:
    """账户历史收益完整重算。"""

    def rebuild_history(
        self,
        account_id: int,
        from_date: Optional[str] = None,
        conn=None,
    ) -> Dict:
        if conn is not None:
            return self._rebuild_with_connection(
                account_id=account_id,
                from_date=from_date,
                conn=conn,
            )

        with db_engine.get_connection() as conn:
            return self._rebuild_with_connection(
                account_id=account_id,
                from_date=from_date,
                conn=conn,
            )

    def try_rebuild_history(
        self,
        account_id: int,
        from_date: Optional[str] = None,
        conn=None,
    ) -> Dict:
        """
        尝试执行完整重算。

        若因行情缺失等可预期原因无法更新历史，不抛异常，直接返回状态摘要，
        以便调用方继续保留当前状态更新结果。
        """
        try:
            return self.rebuild_history(account_id=account_id, from_date=from_date, conn=conn)
        except ValidationError:
            raise
        except Exception as exc:
            logger.exception("账户历史重算异常 account_id=%s", account_id)
            return {
                "updated_rows": 0,
                "from_date": from_date,
                "message": f"账户历史重算失败: {exc}",
            }

    def sync_live_snapshot(
        self,
        account_id: int,
        biz_date: Optional[str] = None,
        conn=None,
    ) -> Dict:
        """
        在历史快照尚未覆盖当前业务日时，写入一条“当日实时快照”。

        该快照用于保证汇总页与当前持仓/现金口径一致，后续若该业务日
        的正式收盘行情入库，完整历史重算会覆盖这条临时记录。
        """
        normalized_date = biz_date or datetime.now().strftime("%Y-%m-%d")
        if conn is not None:
            return self._sync_live_snapshot_with_connection(
                account_id=account_id,
                biz_date=normalized_date,
                conn=conn,
            )

        with db_engine.get_connection() as write_conn:
            return self._sync_live_snapshot_with_connection(
                account_id=account_id,
                biz_date=normalized_date,
                conn=write_conn,
            )

    def _rebuild_with_connection(self, account_id: int, from_date: Optional[str], conn) -> Dict:
        orders = trade_replay_support.load_orders(account_id=account_id, conn=conn)
        cash_flows = trade_replay_support.load_cash_flows(account_id=account_id, conn=conn)
        corporate_actions = trade_replay_support.load_corporate_actions(account_id=account_id, conn=conn)
        trade_calendar = market_dao.get_trade_calendar(conn=conn)
        if not trade_calendar:
            raise ValidationError("交易日历为空，无法执行完整重算")
        latest_market_date = market_dao.get_latest_trade_date_global(conn=conn)
        if not latest_market_date:
            raise ValidationError("行情表为空，无法执行完整重算")

        fact_start_date = trade_replay_support.resolve_start_date(
            orders=orders,
            cash_flows=cash_flows,
            corporate_actions=corporate_actions,
        )
        if not fact_start_date:
            return {"updated_rows": 0, "from_date": from_date, "message": "账户无业务事实数据"}

        start_date = from_date or fact_start_date
        emit_trade_dates = [date for date in trade_calendar if start_date <= date <= latest_market_date]
        if not emit_trade_dates:
            return {"updated_rows": 0, "from_date": start_date, "message": "重算区间内无交易日"}

        trade_dates = [date for date in trade_calendar if fact_start_date <= date <= latest_market_date]
        if not trade_dates:
            return {"updated_rows": 0, "from_date": start_date, "message": "重算区间内无交易日"}

        cash_flow_map = trade_replay_support.group_cash_flows_by_date(cash_flows)
        corporate_action_map = trade_replay_support.group_corporate_actions_by_date(corporate_actions)
        order_map = trade_replay_support.group_orders_by_date(orders)
        asset_codes = sorted(
            {
                *(order["asset_code"] for order in orders),
                *(action["asset_code"] for action in corporate_actions),
            }
        )
        price_map = market_dao.get_close_price_map(
            asset_codes=asset_codes,
            start_date=fact_start_date,
            conn=conn,
        )
        fund_nav_map = market_dao.get_fund_nav_map(
            asset_codes=asset_codes,
            start_date=fact_start_date,
            conn=conn,
        )

        history_rows, missing_quotes = account_history_rebuild_calculator.build_history_rows(
            account_id=account_id,
            trade_dates=trade_dates,
            emit_from_date=start_date,
            cash_flow_map=cash_flow_map,
            corporate_action_map=corporate_action_map,
            order_map=order_map,
            price_map=price_map,
            fund_nav_map=fund_nav_map,
        )
        if missing_quotes:
            return {
                "updated_rows": 0,
                "from_date": start_date,
                "message": "行情不完整，历史收益未更新",
                "missing_quotes": missing_quotes,
            }

        account_history_dao.replace_history_rows(
            account_id=account_id,
            rows=history_rows,
            from_date=start_date,
            conn=conn,
        )
        logger.info(
            "[REBUILD_HISTORY] account_id=%s from_date=%s updated_rows=%s",
            account_id,
            start_date,
            len(history_rows),
        )
        return {
            "updated_rows": len(history_rows),
            "from_date": start_date,
            "message": "账户历史重算成功",
        }

    def _sync_live_snapshot_with_connection(self, account_id: int, biz_date: str, conn) -> Dict:
        latest_complete_row = account_history_dao.get_latest_complete_history(
            account_id=account_id,
            conn=conn,
        )

        if latest_complete_row and latest_complete_row["trade_date"] >= biz_date:
            return {
                "updated_rows": 0,
                "trade_date": latest_complete_row["trade_date"],
                "message": "历史快照已覆盖当前业务日",
            }

        existing_row = account_history_dao.get_history_by_date(
            account_id=account_id,
            trade_date=biz_date,
            conn=conn,
        )
        base_row = account_history_dao.get_latest_complete_history_before(
            account_id=account_id,
            trade_date=biz_date,
            conn=conn,
        )

        if not base_row:
            base_row = account_history_dao.get_previous_day(
                account_id=account_id,
                trade_date=biz_date,
                conn=conn,
            )

        account_row = trade_dao.get_account(account_id=account_id, conn=conn)
        if not account_row:
            return {
                "updated_rows": 0,
                "trade_date": biz_date,
                "message": "账户不存在，无法同步实时快照",
            }

        position_valuation = position_dao.get_account_position_valuation(
            account_id=account_id,
            conn=conn,
        )

        cash_balance = float(account_row.get("cash_balance") or 0.0)
        total_deposit = float(account_row.get("total_deposit") or 0.0)
        total_withdraw = float(account_row.get("total_withdraw") or 0.0)
        acc_profit = float(account_row.get("acc_profit") or 0.0)
        market_value = float(position_valuation["market_value"])
        floating_pnl = float(position_valuation["floating_pnl"])
        total_asset = cash_balance + market_value
        net_investment = total_deposit - total_withdraw
        cum_total_pnl = acc_profit + floating_pnl
        pnl_ratio = cum_total_pnl / net_investment if net_investment > 0 else 0.0

        if base_row:
            base_total_asset = float(base_row["total_asset"] or 0.0)
            external_cash = cash_flow_dao.sum_external_cash_delta(
                account_id=account_id,
                start_date=base_row["trade_date"],
                end_date=biz_date,
                conn=conn,
            )
            # 实时快照必须相对“上一条正式收盘历史”计算，不能叠加上一条 live snapshot 的 daily_return。
            daily_return = (total_asset - base_total_asset) - external_cash
            daily_return_rate = daily_return / base_total_asset if base_total_asset > 0 else 0.0
            account_xirr = float((existing_row or base_row).get("account_xirr") or 0.0)
        else:
            daily_return = 0.0
            daily_return_rate = 0.0
            account_xirr = 0.0

        account_history_dao.upsert_history(
            account_id=account_id,
            trade_date=biz_date,
            cash_balance=cash_balance,
            market_value=market_value,
            total_asset=total_asset,
            total_deposit=total_deposit,
            total_withdraw=total_withdraw,
            total_shares=0.0,
            unit_net_value=0.0,
            daily_return=daily_return,
            daily_return_rate=daily_return_rate,
            net_investment=net_investment,
            total_pnl=cum_total_pnl,
            pnl_ratio=pnl_ratio,
            cum_realized_pnl=acc_profit,
            cum_unrealized_pnl=floating_pnl,
            cum_total_pnl=cum_total_pnl,
            account_xirr=account_xirr,
            is_data_complete=0,
            conn=conn,
        )
        logger.info(
            "[LIVE_HISTORY_SNAPSHOT] account_id=%s biz_date=%s total_asset=%.2f daily_return=%.2f",
            account_id,
            biz_date,
            total_asset,
            daily_return,
        )
        return {
            "updated_rows": 1,
            "trade_date": biz_date,
            "message": "账户实时快照已同步",
        }

account_history_rebuild_service = AccountHistoryRebuildService()
