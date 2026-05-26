from fastapi import APIRouter, Query

from api.models import PaginatedResponse
from core.trade import trade_service

router = APIRouter(prefix="/api/trade-orders", tags=["trade_orders"])


def _display_order_type(item: dict) -> str:
    order_type = item.get("order_type")
    side = item.get("side")
    if order_type == "SPLIT_ADJUST":
        return "份额调整派生"
    if order_type == "DIVIDEND_REINVEST_BUY":
        return "红利再投买入"
    if side == "BUY":
        return "买入"
    if side == "SELL":
        return "卖出"
    return side or "--"


def _normalize_status(status: object) -> str:
    return "ACTIVE" if int(status or 0) == 1 else "CANCELLED"


@router.get("", response_model=PaginatedResponse)
async def get_trade_orders(
    account_id: int = Query(1, description="账户ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量"),
):
    result = trade_service.get_orders(account_id=account_id, page=page, page_size=page_size)
    items = []
    for item in result.get("items", []):
        normalized_status = _normalize_status(item.get("status"))
        realized_return_rate = item.get("realized_return_rate")
        items.append(
            {
                "row_kind": "trade_order",
                "row_id": int(item["order_id"]),
                "order_id": int(item["order_id"]),
                "account_id": int(item["account_id"]),
                "biz_date": item["trade_time"][:10],
                "trade_time": item["trade_time"],
                "asset_code": item["asset_code"],
                "asset_name": item.get("asset_name") or item["asset_code"],
                "side": item["side"],
                "order_type": item.get("order_type"),
                "price": float(item.get("price") or 0.0),
                "volume": float(item.get("volume") or 0.0),
                "amount": float(item.get("amount") or 0.0),
                "commission": float(item.get("commission") or 0.0),
                "tax": float(item.get("tax") or 0.0),
                "realized_pnl": float(item.get("realized_pnl") or 0.0),
                "realized_return_rate": (
                    float(realized_return_rate)
                    if realized_return_rate is not None
                    else None
                ),
                "status": normalized_status,
                "remark": item.get("remark") or "",
                "source_type": item.get("source_type") or "MANUAL",
                "source_ref_id": item.get("source_ref_id"),
                "display_type": _display_order_type(item),
                "editable_via": "trade" if (item.get("source_type") or "MANUAL") != "CORPORATE_ACTION" and normalized_status == "ACTIVE" else "readonly",
            }
        )
    result["items"] = items
    return result
