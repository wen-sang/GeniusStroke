# 文件: api/routers/trade.py
"""
交易管理 API 路由
v2.4.5: 支持持仓查询、指定批次卖出、买入下单
"""
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date
from api.error_helpers import raise_internal_http_error, raise_validation_http_error
from api.services.asset_service import asset_service
from core.trade import trade_service
from utils.validators import ValidationError
from api.models import PaginatedResponse

router = APIRouter(prefix="/api/trade", tags=["trade"])


# ========== 请求/响应模型 ==========

class BuyRequest(BaseModel):
    """买入请求"""
    code: str = Field(..., description="资产代码")
    trade_date: date = Field(..., description="成交日期")
    price: float = Field(..., gt=0, description="成交价格")
    volume: float = Field(..., gt=0, description="成交数量")
    target_rate: float = Field(0.0, ge=0, le=1, description="目标收益率 (0.1=10%)")
    commission: Optional[float] = Field(None, ge=0, description="佣金 (可选，不填自动计算)")
    transfer_fee: float = Field(0.0, ge=0, description="过户费")
    remark: str = Field("", description="备注")


class SellRequest(BaseModel):
    """卖出请求"""
    link_order_id: int = Field(..., description="关联买单ID")
    trade_date: date = Field(..., description="成交日期")
    price: float = Field(..., gt=0, description="成交价格")
    volume: float = Field(..., gt=0, description="成交数量")
    commission: Optional[float] = Field(None, ge=0, description="佣金 (可选)")
    transfer_fee: float = Field(0.0, ge=0, description="过户费")
    tax: Optional[float] = Field(None, ge=0, description="印花税 (可选)")
    remark: str = Field("", description="备注")


class LotResponse(BaseModel):
    """可卖批次响应"""
    order_id: int
    buy_date: str
    buy_price: float
    remain_vol: float
    target_rate: float
    target_price: float


class PositionResponse(BaseModel):
    """持仓响应"""
    asset_code: str
    asset_name: str
    asset_type: str = ""
    total_volume: float
    avg_cost: float
    cost_amount: float
    current_price: float
    market_value: float
    holding_pnl: float
    holding_pnl_rate: float
    realized_pnl: float
    history_total_pnl: float
    updated_at: str


class OrderResponse(BaseModel):
    """订单响应"""
    order_id: int
    asset_code: str
    trade_time: str
    side: str
    price: float
    volume: float
    amount: float
    commission: float
    transfer_fee: float
    tax: float
    realized_pnl: float


# ========== API 端点 ==========

@router.get("/positions", response_model=PaginatedResponse)
async def get_positions(
    account_id: int = Query(1, description="账户ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量")
):
    """
    获取持仓列表（按标的聚合，分页）
    """
    return trade_service.get_positions(account_id, page, page_size)


@router.get("/positions/{code}/lots", response_model=List[LotResponse])
async def get_lots(
    code: str,
    account_id: int = Query(1, description="账户ID")
):
    """
    获取某标的的可卖批次
    """
    lots = trade_service.get_lots(code, account_id)
    
    result = []
    for l in lots:
        result.append(LotResponse(
            order_id=l.order_id,
            buy_date=l.buy_date,
            buy_price=l.buy_price,
            remain_vol=l.remain_vol,
            target_rate=l.target_rate,
            target_price=l.target_price,
        ))
    
    return result


@router.post("/order/buy", response_model=OrderResponse)
async def buy_order(
    req: BuyRequest,
    account_id: int = Query(1, description="账户ID"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    买入下单
    """
    try:
        asset = asset_service.get_asset(req.code)
        if not asset:
            raise ValidationError("资产代码不存在，请先新增基础档案")
        order = trade_service.buy(
            account_id=account_id,
            asset_code=req.code,
            trade_date=req.trade_date.isoformat(),
            price=req.price,
            volume=req.volume,
            target_rate=req.target_rate,
            commission=req.commission,
            transfer_fee=req.transfer_fee,
            remark=req.remark,
            idempotency_key=idempotency_key,
        )
        
        return OrderResponse(
            order_id=order.order_id,
            asset_code=order.asset_code,
            trade_time=order.trade_time,
            side=order.side,
            price=order.price,
            volume=order.volume,
            amount=order.amount,
            commission=order.commission,
            transfer_fee=order.transfer_fee,
            tax=order.tax,
            realized_pnl=order.realized_pnl,
        )
    except ValidationError as e:
        raise_validation_http_error(
            "买入参数校验失败 account_id=%s code=%s detail=%s",
            e,
            account_id,
            req.code,
        )
    except Exception:
        raise_internal_http_error("买入下单失败 account_id=%s code=%s", "下单失败", account_id, req.code)


@router.post("/order/sell", response_model=OrderResponse)
async def sell_order(
    req: SellRequest,
    account_id: int = Query(1, description="账户ID"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    卖出下单（指定批次）
    """
    try:
        order = trade_service.sell(
            account_id=account_id,
            link_order_id=req.link_order_id,
            trade_date=req.trade_date.isoformat(),
            price=req.price,
            volume=req.volume,
            commission=req.commission,
            transfer_fee=req.transfer_fee,
            tax=req.tax,
            remark=req.remark,
            idempotency_key=idempotency_key,
        )
        
        return OrderResponse(
            order_id=order.order_id,
            asset_code=order.asset_code,
            trade_time=order.trade_time,
            side=order.side,
            price=order.price,
            volume=order.volume,
            amount=order.amount,
            commission=order.commission,
            transfer_fee=order.transfer_fee,
            tax=order.tax,
            realized_pnl=order.realized_pnl,
        )
    except ValidationError as e:
        raise_validation_http_error(
            "卖出参数校验失败 account_id=%s link_order_id=%s detail=%s",
            e,
            account_id,
            req.link_order_id,
        )
    except Exception:
        raise_internal_http_error(
            "卖出下单失败 account_id=%s link_order_id=%s",
            "下单失败",
            account_id,
            req.link_order_id,
        )


class OrderUpdateRequest(BaseModel):
    """订单修改请求"""
    trade_time: str = Field(..., description="交易时间")
    side: str = Field(..., description="交易类型")
    price: float = Field(..., gt=0, description="成交价格")
    volume: float = Field(..., gt=0, description="成交数量")
    commission: float = Field(..., ge=0, description="佣金")
    transfer_fee: float = Field(0.0, ge=0, description="过户费")
    tax: Optional[float] = Field(None, ge=0, description="印花税")
    remark: Optional[str] = Field("", description="备注")

@router.put("/order/{order_id}")
async def update_order(
    order_id: int, 
    req: OrderUpdateRequest, 
    account_id: int = Query(1, description="账户ID")
):
    """
    修改订单信息
    """
    try:
        trade_service.update_order(
            account_id=account_id,
            order_id=order_id,
            trade_time=req.trade_time,
            side=req.side,
            price=req.price,
            volume=req.volume,
            commission=req.commission,
            transfer_fee=req.transfer_fee,
            tax=req.tax,
            remark=req.remark
        )
        return {"success": True, "message": "订单修改成功"}
    except ValidationError as e:
        raise_validation_http_error(
            "订单修改参数校验失败 account_id=%s order_id=%s detail=%s",
            e,
            account_id,
            order_id,
        )
    except Exception:
        raise_internal_http_error("订单修改失败 account_id=%s order_id=%s", "订单修改失败", account_id, order_id)


@router.get("/orders", response_model=PaginatedResponse)
async def get_orders(
    account_id: int = Query(1, description="账户ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量")
):
    """
    获取订单列表 (交易记录)
    """
    return trade_service.get_orders(account_id, page, page_size)
