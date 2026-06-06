"""企业事件预览计算辅助模块。

从 service.py 中提取的预览相关纯计算逻辑，包括：
- 持仓回放与合格批次加载
- 分红现金计算
- 红利再投计算
- 预览数据构建
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from config.constants import AssetType
from core.trade.replay_support import ReplayLotState, ReplayState, trade_replay_support
from utils.decimal_utils import (
    floor_to_int_qty,
    quantize_amount,
    quantize_cash,
    quantize_exchange_qty,
    quantize_qty,
    to_decimal,
)
from utils.validators import ValidationError


EXCHANGE_TRADED_ASSET_TYPES = {AssetType.STOCK, AssetType.ETF, AssetType.LOF}


def is_exchange_traded_asset(asset_type: Optional[str]) -> bool:
    return asset_type in EXCHANGE_TRADED_ASSET_TYPES


def previous_calendar_date(effective_date: str) -> str:
    """返回生效日的前一个自然日（T-1）。"""
    dt = datetime.strptime(effective_date, "%Y-%m-%d").date()
    return (dt - timedelta(days=1)).strftime("%Y-%m-%d")


def load_eligible_lots(
    account_id: int,
    asset_code: str,
    effective_date: str,
    record_date: Optional[str],
    conn,
) -> List[ReplayLotState]:
    """通过交易回放，加载权益资格日仍持有的合格批次。"""
    eligibility_date = record_date or previous_calendar_date(effective_date)
    orders = trade_replay_support.load_orders(account_id=account_id, conn=conn, as_of_date=eligibility_date)
    cash_flows = trade_replay_support.load_cash_flows(account_id=account_id, conn=conn, as_of_date=eligibility_date)
    corporate_actions = trade_replay_support.load_corporate_actions(
        account_id=account_id,
        conn=conn,
        as_of_date=eligibility_date,
    )
    replay_state = ReplayState(account_id=account_id)
    events = trade_replay_support.build_replay_events(
        orders=orders,
        cash_flows=cash_flows,
        corporate_actions=corporate_actions,
    )
    for event in events:
        if event["event_kind"] == "corporate_action":
            trade_replay_support.apply_corporate_action(replay_state, event["payload"])
        elif event["event_kind"] == "cash_flow":
            trade_replay_support.apply_cash_flow(replay_state, event["payload"])
        else:
            trade_replay_support.apply_order(replay_state, event["payload"])
    return [
        lot
        for lot in replay_state.buy_lots.values()
        if lot.asset_code == asset_code and lot.remain_vol > 0
    ]


def calculate_dividend_cash(
    eligible_qty: Decimal,
    cash_base_unit: Optional[str],
    cash_base_qty: Optional[Decimal],
    cash_amount: Optional[Decimal],
) -> Decimal:
    """根据合格份额和分红口径计算应发分红现金。"""
    if cash_base_unit == "PER_SHARE":
        return quantize_amount(eligible_qty * (cash_amount or Decimal("0")))
    if cash_base_unit == "PER_10_SHARES":
        return quantize_amount((eligible_qty / Decimal("10")) * (cash_amount or Decimal("0")))
    if cash_base_unit == "PER_N_SHARES":
        if cash_base_qty is None or cash_base_qty <= 0:
            raise ValidationError("每 N 份分红必须填写分红基准数量")
        return quantize_amount((eligible_qty / cash_base_qty) * (cash_amount or Decimal("0")))
    raise ValidationError("分红口径不合法")


def calculate_reinvest_values(
    dividend_cash: Decimal,
    reinvest_price: Optional[Decimal],
    rounding_policy: Optional[str],
) -> tuple[Decimal, Decimal, Decimal]:
    """计算红利再投的新增份额、实际使用现金和余额。"""
    if reinvest_price is None or reinvest_price <= 0:
        raise ValidationError("再投价格必须大于 0")
    raw_volume = dividend_cash / reinvest_price if reinvest_price > 0 else Decimal("0")
    if rounding_policy == "KEEP_DECIMAL":
        reinvest_volume = quantize_qty(raw_volume)
    elif rounding_policy == "ROUND_DOWN":
        reinvest_volume = floor_to_int_qty(raw_volume)
    else:
        raise ValidationError("份额处理策略不合法")
    dividend_cash_used = quantize_amount(reinvest_volume * reinvest_price)
    cash_residual = quantize_amount(dividend_cash - dividend_cash_used)
    return reinvest_volume, dividend_cash_used, cash_residual


def build_preview(
    account_id: int,
    asset_code: str,
    asset_type: Optional[str],
    action_type: str,
    effective_date: str,
    record_date: Optional[str],
    cash_base_unit: Optional[str],
    cash_base_qty: Optional[Decimal],
    cash_amount: Optional[Decimal],
    ratio_from: Optional[int],
    ratio_to: Optional[int],
    reinvest_price: Optional[Decimal],
    rounding_policy: Optional[str],
    conn,
) -> Dict:
    """构建企业事件预览数据，包含合格份额、分红现金、再投份额等。"""
    exchange_traded = is_exchange_traded_asset(asset_type)
    lots = load_eligible_lots(
        account_id=account_id,
        asset_code=asset_code,
        effective_date=effective_date,
        record_date=record_date,
        conn=conn,
    )
    eligible_qty = sum((to_decimal(lot.remain_vol) for lot in lots), Decimal("0"))
    if exchange_traded:
        eligible_qty = quantize_exchange_qty(eligible_qty)
    affected_lot_count = len(lots)
    dividend_cash = Decimal("0")
    reinvest_volume = Decimal("0")
    dividend_cash_used = Decimal("0")
    cash_residual = Decimal("0")
    split_ratio_text = None

    if action_type == "SPLIT":
        split_ratio_text = f"{ratio_from}:{ratio_to}"
    else:
        dividend_cash = calculate_dividend_cash(
            eligible_qty=eligible_qty,
            cash_base_unit=cash_base_unit,
            cash_base_qty=cash_base_qty,
            cash_amount=cash_amount,
        )
    if action_type == "DIVIDEND_REINVEST":
        reinvest_volume, dividend_cash_used, cash_residual = calculate_reinvest_values(
            dividend_cash=dividend_cash,
            reinvest_price=reinvest_price,
            rounding_policy=rounding_policy,
        )
        if exchange_traded:
            reinvest_volume = floor_to_int_qty(reinvest_volume)
            dividend_cash_used = quantize_cash(reinvest_volume * (reinvest_price or Decimal("0")))
            cash_residual = quantize_cash(dividend_cash - dividend_cash_used)

    warnings: List[str] = []
    if eligible_qty <= 0:
        warnings.append("生效日前无可参与持仓，事件可先录入为待确认，待后续确认时再判定是否生效")

    quantity_quantizer = quantize_exchange_qty if exchange_traded else quantize_qty
    amount_quantizer = quantize_cash if exchange_traded else quantize_amount
    return {
        "exchange_traded": exchange_traded,
        "eligible_qty": quantity_quantizer(eligible_qty),
        "affected_lot_count": affected_lot_count,
        "split_ratio_text": split_ratio_text,
        "dividend_cash": amount_quantizer(dividend_cash),
        "reinvest_volume": quantity_quantizer(reinvest_volume),
        "dividend_cash_used": amount_quantizer(dividend_cash_used),
        "cash_residual": amount_quantizer(cash_residual),
        "warnings": warnings,
    }


def ensure_preview_has_eligible_holding(action_type: str, preview: Dict) -> None:
    """确认预览结果中存在可参与持仓，否则抛出校验异常。"""
    if preview["eligible_qty"] <= 0:
        raise ValidationError(f"{action_type} 在生效日前无可参与持仓")
    if action_type == "DIVIDEND_REINVEST" and preview["dividend_cash_used"] <= 0:
        raise ValidationError("红利再投生成的新增份额为 0，无法创建")
