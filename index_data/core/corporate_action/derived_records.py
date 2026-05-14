"""企业事件派生记录管理模块。

从 service.py 中提取的派生记录写入、清除、重建触发和审计日志逻辑。
"""
from __future__ import annotations

from typing import Dict

from dao.trade_dao import trade_dao
from core.trade.history_rebuild_service import account_history_rebuild_service
from core.trade.models import CashFlow, Order
from core.trade.rebuild_service import account_rebuild_service
from dao.cash_flow_dao import cash_flow_dao

from .dao import corporate_action_dao
from .models import CorporateAction


def clear_derived_records(action_id: int, conn) -> None:
    """撤销指定企业事件的所有派生现金流水和派生订单。"""
    corporate_action_dao.cancel_derived_cash_flows(action_id=action_id, conn=conn)
    corporate_action_dao.cancel_derived_orders(action_id=action_id, conn=conn)


def rebuild_derived_records(action: CorporateAction, preview: Dict, conn) -> None:
    """根据企业事件和预览数据，重建派生记录（订单/现金流水）。

    先清除旧的派生记录，再根据事件类型创建新的：
    - SPLIT: 创建 ADJUST 类型的份额调整订单
    - CASH_DIVIDEND: 创建 DIVIDEND 类型的现金流入
    - DIVIDEND_REINVEST: 创建 DIVIDEND 现金流入 + BUY 再投订单
    """
    clear_derived_records(action_id=action.action_id, conn=conn)
    if action.status != "CONFIRMED":
        return

    if action.action_type == "SPLIT":
        split_delta = float(preview["eligible_qty"]) * (
            (float(action.ratio_to or 0) / float(action.ratio_from or 1)) - 1.0
        )
        order = Order(
            account_id=action.account_id,
            asset_code=action.asset_code,
            trade_time=f"{action.effective_date} 00:00:00",
            side="ADJUST",
            order_type="SPLIT_ADJUST",
            price=0.0,
            volume=split_delta,
            amount=0.0,
            commission=0.0,
            tax=0.0,
            remain_vol=0.0,
            target_rate=0.0,
            realized_pnl=0.0,
            status=1,
            remark="企业事件派生: SPLIT",
            source_type="CORPORATE_ACTION",
            source_ref_id=str(action.action_id),
        )
        trade_dao.insert_order(order=order, conn=conn)
        return

    cash_flow = CashFlow(
        account_id=action.account_id,
        biz_date=action.effective_date,
        flow_type="DIVIDEND",
        direction="IN",
        amount=float(preview["dividend_cash"]),
        status="ACTIVE",
        remark=f"企业事件派生: {action.action_type}",
        source_type="CORPORATE_ACTION",
        source_ref_id=str(action.action_id),
    )
    cash_flow_dao.insert_cash_flow(cash_flow, conn=conn)

    if action.action_type == "DIVIDEND_REINVEST":
        order = Order(
            account_id=action.account_id,
            asset_code=action.asset_code,
            trade_time=f"{action.effective_date} 00:00:00",
            side="BUY",
            order_type="DIVIDEND_REINVEST_BUY",
            price=float(action.reinvest_price or 0.0),
            volume=float(preview["reinvest_volume"]),
            amount=float(preview["dividend_cash_used"]),
            commission=0.0,
            tax=0.0,
            remain_vol=float(preview["reinvest_volume"]),
            target_rate=0.0,
            realized_pnl=0.0,
            status=1,
            remark="企业事件派生: DIVIDEND_REINVEST",
            source_type="CORPORATE_ACTION",
            source_ref_id=str(action.action_id),
        )
        trade_dao.insert_order(order=order, conn=conn)


def run_rebuilds(account_id: int, effective_date: str, conn) -> None:
    """触发账户当前状态重建和历史重算。"""
    account_rebuild_service.rebuild_current_state(account_id=account_id, conn=conn)
    account_history_rebuild_service.try_rebuild_history(
        account_id=account_id,
        from_date=effective_date,
        conn=conn,
    )
    account_history_rebuild_service.sync_live_snapshot(
        account_id=account_id,
        biz_date=effective_date,
        conn=conn,
    )


def insert_audit_log(
    account_id: int,
    action_type: str,
    amount_change: float,
    remark: str,
    conn,
) -> None:
    """写入企业事件相关审计日志。"""
    trade_dao.insert_audit_log(
        account_id=account_id,
        order_id=None,
        action_type=action_type,
        before_cash=0.0,
        after_cash=0.0,
        amount_change=amount_change,
        remark=remark,
        conn=conn,
    )
