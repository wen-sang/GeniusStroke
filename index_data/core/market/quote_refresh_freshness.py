"""
Pure freshness helpers for quote refresh orchestration.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Dict, Optional


def summarize_cached_quotes(cached_quotes: Dict[str, dict]) -> dict:
    newest_quote_date = None
    newest_refresh_time = None
    for item in cached_quotes.values():
        quote_date = item.get("quote_date")
        refreshed_at = item.get("refreshed_at")
        if quote_date and (newest_quote_date is None or quote_date > newest_quote_date):
            newest_quote_date = quote_date
        if refreshed_at and (newest_refresh_time is None or refreshed_at > newest_refresh_time):
            newest_refresh_time = refreshed_at
    return {
        "newest_quote_date": newest_quote_date,
        "newest_refresh_time": newest_refresh_time,
    }


def is_quote_stale(
    item: Optional[dict],
    refresh_context: dict,
    now: datetime,
    ttl_seconds: int,
    market_close_hour: int,
) -> bool:
    if not item:
        return True

    refreshed_at = item.get("refreshed_at")
    if not refreshed_at:
        return True

    try:
        refreshed_dt = datetime.strptime(refreshed_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return True

    if (now - refreshed_dt).total_seconds() >= ttl_seconds:
        return True

    latest_trade_date = refresh_context.get("latest_trade_date")
    today = refresh_context.get("today")
    market_closed = refresh_context.get("market_closed")
    quote_date = item.get("quote_date")

    if latest_trade_date:
        if not refresh_context.get("is_trade_day"):
            return quote_date != latest_trade_date

        if market_closed:
            if quote_date != latest_trade_date:
                return True
            if quote_date == today and refreshed_dt.time() < time(market_close_hour, 0):
                return True

    return False
