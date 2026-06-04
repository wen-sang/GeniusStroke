# core/trade/models.py - 交易领域模型
"""
交易管理领域模型定义
v2.4.5: 支持指定批次卖出
"""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Order:
    """交易订单模型"""
    order_id: Optional[int] = None
    order_no: Optional[str] = None
    account_id: int = 1
    asset_code: str = ""
    trade_time: str = ""
    side: str = ""  # BUY, SELL
    order_type: Optional[str] = None  # MANUAL_BUY, MANUAL_SELL, SPLIT_ADJUST, DIVIDEND_REINVEST_BUY
    price: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    commission: float = 0.0
    transfer_fee: float = 0.0
    tax: float = 0.0
    remain_vol: float = 0.0  # 剩余可用份额 (仅 BUY)
    link_order_id: Optional[int] = None  # 关联买单ID (仅 SELL)
    target_rate: float = 0.0  # 目标收益率 (仅 BUY)
    realized_pnl: float = 0.0  # 实现盈亏 (仅 SELL)
    status: int = 1  # 1=有效, 0=已撤单
    remark: str = ""
    source_type: Optional[str] = None
    source_ref_id: Optional[str] = None
    updated_at: Optional[str] = None
    created_at: Optional[str] = None
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'order_id': self.order_id,
            'order_no': self.order_no,
            'account_id': self.account_id,
            'asset_code': self.asset_code,
            'trade_time': self.trade_time,
            'side': self.side,
            'order_type': self.order_type,
            'price': self.price,
            'volume': self.volume,
            'amount': self.amount,
            'commission': self.commission,
            'transfer_fee': self.transfer_fee,
            'tax': self.tax,
            'remain_vol': self.remain_vol,
            'link_order_id': self.link_order_id,
            'target_rate': self.target_rate,
            'realized_pnl': self.realized_pnl,
            'status': self.status,
            'remark': self.remark,
            'source_type': self.source_type,
            'source_ref_id': self.source_ref_id,
            'updated_at': self.updated_at,
            'created_at': self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Order':
        """从字典创建订单对象"""
        return cls(
            order_id=data.get('order_id'),
            order_no=data.get('order_no'),
            account_id=data.get('account_id', 1),
            asset_code=data.get('asset_code', ''),
            trade_time=data.get('trade_time', ''),
            side=data.get('side', ''),
            order_type=data.get('order_type'),
            price=data.get('price', 0.0),
            volume=data.get('volume', 0.0),
            amount=data.get('amount', 0.0),
            commission=data.get('commission', 0.0),
            transfer_fee=data.get('transfer_fee', 0.0),
            tax=data.get('tax', 0.0),
            remain_vol=data.get('remain_vol', 0.0),
            link_order_id=data.get('link_order_id'),
            target_rate=data.get('target_rate', 0.0),
            realized_pnl=data.get('realized_pnl', 0.0),
            status=data.get('status', 1),
            remark=data.get('remark', ''),
            source_type=data.get('source_type'),
            source_ref_id=data.get('source_ref_id'),
            updated_at=data.get('updated_at'),
            created_at=data.get('created_at'),
        )


@dataclass
class Position:
    """持仓汇总模型 (按标的聚合)"""
    asset_code: str = ""
    asset_name: str = ""
    total_volume: float = 0.0  # 总持仓量
    avg_cost: float = 0.0  # 平均成本
    cost_amount: float = 0.0  # 持仓成本
    market_value: float = 0.0  # 持有市值
    current_price: float = 0.0  # 当前价格
    total_pnl: float = 0.0  # 持有收益/浮动盈亏
    pnl_rate: float = 0.0  # 持有收益率
    realized_pnl: float = 0.0  # 历史已实现收益
    history_total_pnl: float = 0.0  # 历史累计收益 = 已实现 + 当前持有收益
    updated_at: str = ""  # 持仓快照更新时间
    lots: List[dict] = field(default_factory=list)  # 可卖批次列表


@dataclass 
class AccountSummary:
    """账户汇总模型"""
    account_id: int = 1
    account_name: str = "Default"
    broker_name: str = ""
    cash_balance: float = 0.0  # 可用现金
    total_market_value: float = 0.0  # 总市值
    total_asset: float = 0.0  # 总资产 (现金+市值)
    total_deposit: float = 0.0  # 累计入金
    total_withdraw: float = 0.0  # 累计出金
    acc_profit: float = 0.0  # 累计已实现收益
    floating_pnl: float = 0.0  # 浮动盈亏
    daily_return: float = 0.0  # 当日收益
    daily_return_rate: float = 0.0  # 当日收益率
    history_total_pnl: float = 0.0  # 历史累计收益
    history_total_pnl_rate: float = 0.0  # 历史累计收益率
    account_xirr: Optional[float] = None  # 账户累计收益率 (XIRR)
    data_updated_to: Optional[str] = None  # 历史资产快照最新交易日
    commission_rate: float = 0.00025  # 佣金费率
    commission_min: float = 5.0  # 最低佣金
    stamp_duty_rate: float = 0.001  # 印花税率


@dataclass
class Lot:
    """可卖批次模型"""
    order_id: int = 0
    buy_date: str = ""
    buy_price: float = 0.0
    remain_vol: float = 0.0
    target_rate: float = 0.0
    target_price: float = 0.0
    current_pnl: float = 0.0


@dataclass
class CashFlow:
    """账户资金流水模型"""
    flow_id: Optional[int] = None
    account_id: int = 1
    biz_date: str = ""
    flow_type: str = ""  # DEPOSIT, WITHDRAW, ADJUST
    direction: str = "IN"  # IN, OUT
    amount: float = 0.0
    status: str = "ACTIVE"  # ACTIVE, CANCELLED
    remark: str = ""
    source_type: Optional[str] = None
    source_ref_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "flow_id": self.flow_id,
            "account_id": self.account_id,
            "biz_date": self.biz_date,
            "flow_type": self.flow_type,
            "direction": self.direction,
            "amount": self.amount,
            "status": self.status,
            "remark": self.remark,
            "source_type": self.source_type,
            "source_ref_id": self.source_ref_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CashFlow":
        """从字典创建资金流水对象"""
        return cls(
            flow_id=data.get("flow_id"),
            account_id=data.get("account_id", 1),
            biz_date=data.get("biz_date", ""),
            flow_type=data.get("flow_type", ""),
            direction=data.get("direction", "IN"),
            amount=data.get("amount", 0.0),
            status=data.get("status", "ACTIVE"),
            remark=data.get("remark", ""),
            source_type=data.get("source_type"),
            source_ref_id=data.get("source_ref_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
