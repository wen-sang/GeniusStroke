"""
资金流水服务

负责账户资金流水事实写入与基础查询。
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Dict, List, Optional

from dao.cash_flow_dao import cash_flow_dao
from utils.logger import logger
from utils.validators import ValidationError

from dao.trade_dao import trade_dao
from .history_rebuild_service import account_history_rebuild_service
from .models import CashFlow
from .mutation_rebuild_orchestrator import TradeMutationRebuildOrchestrator
from .rebuild_service import account_rebuild_service
from core.db_engine import db_engine


class CashFlowService:
    """资金流水业务服务。"""

    VALID_FLOW_TYPES = {"DEPOSIT", "WITHDRAW", "ADJUST"}

    def __init__(self) -> None:
        self.cash_flow_dao = cash_flow_dao
        self.trade_dao = trade_dao
        self.mutation_rebuild_orchestrator = TradeMutationRebuildOrchestrator(
            current_rebuild_service=account_rebuild_service,
            history_rebuild_service=account_history_rebuild_service,
        )

    def create_cash_flow(
        self,
        account_id: int,
        flow_type: str,
        amount: float,
        remark: str = "",
        biz_date: Optional[str] = None,
        source_type: str = "MANUAL",
        source_ref_id: Optional[str] = None,
        adjust_direction: Optional[str] = None,
    ) -> CashFlow:
        """
        创建一笔资金流水，并同步兼容当前账户缓存。

        `adjust_direction` 仅在 `ADJUST` 时使用，支持 `IN` / `OUT`。
        """
        normalized_type = flow_type.upper()
        if normalized_type not in self.VALID_FLOW_TYPES:
            raise ValidationError(f"不支持的资金流水类型: {flow_type}")

        if amount <= 0:
            raise ValidationError("资金流水金额必须大于 0")

        normalized_date = biz_date or datetime.now().strftime("%Y-%m-%d")
        cash_delta = self._resolve_cash_delta(
            flow_type=normalized_type,
            amount=amount,
            adjust_direction=adjust_direction,
        )

        with db_engine.get_connection() as conn:
            account = self.trade_dao.get_or_create_account(account_id, conn=conn)
            before_cash = float(account.get("cash_balance", 0.0) or 0.0)
            after_cash = before_cash + cash_delta
            if after_cash < 0:
                raise ValidationError(
                    f"资金变动后现金不能为负数: 当前 {before_cash:.2f}, 变动 {cash_delta:.2f}"
                )

            cash_flow = CashFlow(
                account_id=account_id,
                biz_date=normalized_date,
                flow_type=normalized_type,
                direction="IN" if cash_delta >= 0 else "OUT",
                amount=amount,
                remark=remark or normalized_type,
                source_type=source_type,
                source_ref_id=source_ref_id,
            )
            cash_flow.flow_id = self.cash_flow_dao.insert_cash_flow(cash_flow, conn=conn)
            self.trade_dao.insert_audit_log(
                account_id=account_id,
                order_id=None,
                action_type=normalized_type,
                before_cash=before_cash,
                after_cash=after_cash,
                amount_change=cash_delta,
                remark=remark or normalized_type,
                conn=conn,
            )
            rebuild_result = self.mutation_rebuild_orchestrator.refresh_after_mutation(
                account_id=account_id,
                from_date=normalized_date,
                live_snapshot_date=normalized_date,
                conn=conn,
            )
            history_result = rebuild_result["history_result"]
            live_snapshot_result = rebuild_result["live_snapshot_result"]

        logger.info(
            "[CASH_FLOW] Account:%s | Type:%s | Amount:%s | Cash: %s -> %s | history=%s | live=%s",
            account_id,
            normalized_type,
            amount,
            before_cash,
            after_cash,
            history_result.get("message"),
            live_snapshot_result.get("message"),
        )
        return cash_flow

    def list_cash_flows(
        self,
        account_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        flow_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """查询资金流水列表。"""
        normalized_type = flow_type.upper() if flow_type else None
        if normalized_type and normalized_type not in self.VALID_FLOW_TYPES:
            raise ValidationError(f"不支持的资金流水类型: {flow_type}")

        return self.cash_flow_dao.list_cash_flows(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            flow_type=normalized_type,
            limit=limit,
        )

    def deposit(
        self,
        account_id: int,
        amount: float,
        remark: str = "",
        biz_date: Optional[str] = None,
    ) -> CashFlow:
        """手工入金。"""
        return self.create_cash_flow(
            account_id=account_id,
            flow_type="DEPOSIT",
            amount=amount,
            remark=remark or "入金",
            biz_date=biz_date,
        )

    def withdraw(
        self,
        account_id: int,
        amount: float,
        remark: str = "",
        biz_date: Optional[str] = None,
    ) -> CashFlow:
        """手工出金。"""
        return self.create_cash_flow(
            account_id=account_id,
            flow_type="WITHDRAW",
            amount=amount,
            remark=remark or "出金",
            biz_date=biz_date,
        )

    def adjust(
        self,
        account_id: int,
        amount: float,
        direction: str,
        remark: str = "",
        biz_date: Optional[str] = None,
    ) -> CashFlow:
        """手工调账。"""
        return self.create_cash_flow(
            account_id=account_id,
            flow_type="ADJUST",
            amount=amount,
            remark=remark or "调账",
            biz_date=biz_date,
            adjust_direction=direction,
        )

    def _resolve_cash_delta(
        self,
        flow_type: str,
        amount: float,
        adjust_direction: Optional[str],
    ) -> float:
        """将资金流水映射为账户现金增减值。"""
        if flow_type == "DEPOSIT":
            return amount
        if flow_type == "WITHDRAW":
            return -amount
        if flow_type == "ADJUST":
            normalized_direction = (adjust_direction or "").upper()
            if normalized_direction not in {"IN", "OUT"}:
                raise ValidationError("调账必须指定方向: IN 或 OUT")
            return amount if normalized_direction == "IN" else -amount
        raise ValidationError(f"未知的资金流水类型: {flow_type}")


cash_flow_service = CashFlowService()
