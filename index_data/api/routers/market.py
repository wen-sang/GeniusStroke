# 文件: api/routers/market.py
from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool
from typing import Dict, Any
import time
from threading import Lock
from api.error_helpers import raise_internal_http_error
from api.models import PaginatedResponse
from api.services.market_service import MarketService
from core.market import quote_refresh_service
from utils.logger import logger

router = APIRouter(prefix="/api", tags=["market"])

_realtime_stats_lock = Lock()
_realtime_stats = {
    "window_start": time.time(),
    "calls": 0,
    "codes_total": 0,
    "missing_total": 0,
    "db_filled_total": 0,
    "db_errors": 0,
}
_REALTIME_STATS_LOG_EVERY = 50


def _record_realtime_fallback_stats(total_codes: int, missing_count: int, db_filled_count: int, db_error: bool) -> None:
    """仅用于性能观测，不改变接口返回语义。"""
    with _realtime_stats_lock:
        _realtime_stats["calls"] += 1
        _realtime_stats["codes_total"] += total_codes
        _realtime_stats["missing_total"] += missing_count
        _realtime_stats["db_filled_total"] += db_filled_count
        if db_error:
            _realtime_stats["db_errors"] += 1

        calls = _realtime_stats["calls"]
        if calls % _REALTIME_STATS_LOG_EVERY != 0:
            return

        elapsed = max(time.time() - _realtime_stats["window_start"], 1e-6)
        codes_total = _realtime_stats["codes_total"]
        missing_total = _realtime_stats["missing_total"]
        db_filled_total = _realtime_stats["db_filled_total"]
        db_errors = _realtime_stats["db_errors"]

    fallback_ratio = (missing_total / codes_total) if codes_total else 0.0
    fill_ratio = (db_filled_total / missing_total) if missing_total else 0.0
    qps = calls / elapsed
    logger.info(
        "[RealtimeStats] calls=%s qps=%.2f codes=%s missing=%s fallback_ratio=%.2f%% db_fill_ratio=%.2f%% db_errors=%s",
        calls,
        qps,
        codes_total,
        missing_total,
        fallback_ratio * 100,
        fill_ratio * 100,
        db_errors,
    )


@router.get("/market", response_model=PaginatedResponse)
async def get_market_data(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(60, ge=1, le=100, description="每页数量"),
    group: str = "index",
):
    """
    获取市场行情数据

    - **page**: 页码（默认1）
    - **page_size**: 每页数量（默认60，最大100）
    - **group**: 资产分组（默认 index，保持旧接口行为）
    """
    if group not in {"index", "non_index"}:
        raise HTTPException(status_code=422, detail="group must be index or non_index")

    service = MarketService()
    try:
        return service.get_market_data(page=page, page_size=page_size, group=group)
    except Exception:
        raise_internal_http_error(
            "市场数据查询失败 page=%s page_size=%s group=%s",
            "市场数据查询失败",
            page,
            page_size,
            group,
        )


@router.get("/market/realtime")
async def get_realtime_quotes(
    codes: str = Query(..., description="股票/ETF代码，逗号分隔 (如: 513050,510300)"),
    force_refresh: bool = Query(False, description="是否强制刷新外部行情"),
) -> Dict[str, Any]:
    """
    获取实时行情（使用 efinance）

    - **codes**: 代码列表，逗号分隔
    - **返回**: 各代码的实时行情，附带刷新提示元数据
    """
    code_list = [c.strip() for c in codes.split(',') if c.strip()]

    if not code_list:
        return {"quotes": {}, "meta": {"message": "未提供有效代码"}}
    try:
        payload = await run_in_threadpool(
            quote_refresh_service.get_quotes_payload,
            code_list,
            force_refresh=force_refresh,
        )
    except Exception:
        logger.exception(
            "实时行情接口异常，回退缓存/数据库 codes=%s force_refresh=%s",
            ",".join(code_list),
            force_refresh,
        )
        try:
            payload = quote_refresh_service.build_degraded_payload(code_list)
        except Exception:
            raise_internal_http_error(
                "实时行情降级失败 codes=%s force_refresh=%s",
                "实时行情查询失败",
                ",".join(code_list),
                force_refresh,
            )

    result = payload.get("quotes", {})
    missing_codes = [c for c in code_list if c not in result]
    db_filled_count = sum(1 for item in result.values() if item.get("origin_source") == "market_db_fallback")
    db_error = False
    if missing_codes:
        logger.warning("部分代码未返回行情数据 codes=%s", ",".join(missing_codes))

    _record_realtime_fallback_stats(
        total_codes=len(code_list),
        missing_count=len(missing_codes),
        db_filled_count=db_filled_count,
        db_error=db_error,
    )
    return payload
