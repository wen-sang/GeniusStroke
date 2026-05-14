"""
Pure payload helpers for quote refresh responses.
"""
from __future__ import annotations

from typing import Dict, Optional


TEXT_FIELDS = {
    "asset_code",
    "asset_name",
    "name",
    "quote_date",
    "source",
    "refreshed_at",
    "updated_at",
    "created_at",
}

QUOTE_NUMERIC_FIELDS = (
    "price",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "change_pct",
    "change_amt",
    "turnover",
)


def to_native_number(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (int, float)):
        return value
    return value


def to_native_text(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, bytes):
        for encoding in ("utf-8", "gb18030"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def sanitize_quote_item(item: Optional[dict]) -> dict:
    if not item:
        return {}
    sanitized = dict(item)
    for field in TEXT_FIELDS:
        if field in sanitized:
            sanitized[field] = to_native_text(sanitized.get(field))
    return sanitized


def sanitize_quotes_map(quotes: Optional[Dict[str, dict]]) -> Dict[str, dict]:
    if not quotes:
        return {}
    sanitized: Dict[str, dict] = {}
    for code, item in quotes.items():
        normalized_code = to_native_text(code)
        sanitized_item = sanitize_quote_item(item)
        if normalized_code:
            sanitized[normalized_code] = sanitized_item
    return sanitized


def build_quote_snapshot(
    code: str,
    asset_name,
    quote_date,
    source: str,
    is_realtime: bool,
    now: str,
    cached: Optional[dict] = None,
    values: Optional[Dict[str, object]] = None,
) -> dict:
    cached_item = sanitize_quote_item(cached)
    merged = {
        "asset_code": code,
        "asset_name": to_native_text(asset_name) or cached_item.get("asset_name") or code,
        "quote_date": to_native_text(quote_date) or cached_item.get("quote_date"),
        "source": source,
        "is_realtime": is_realtime,
        "refreshed_at": now,
        "updated_at": now,
        "created_at": now,
    }
    raw_values = values or {}
    for field in QUOTE_NUMERIC_FIELDS:
        value = raw_values.get(field)
        merged[field] = value if value is not None else cached_item.get(field)
    return merged


def build_response(item: dict, source: str) -> dict:
    sanitized_item = sanitize_quote_item(item)
    stored_source = to_native_text(sanitized_item.get("source")) or source
    return {
        "price": to_native_number(sanitized_item.get("price")),
        "name": to_native_text(
            sanitized_item.get("asset_name")
            or sanitized_item.get("name")
            or sanitized_item.get("asset_code")
        ),
        "high": to_native_number(sanitized_item.get("high")),
        "low": to_native_number(sanitized_item.get("low")),
        "volume": to_native_number(sanitized_item.get("volume")),
        "amount": to_native_number(sanitized_item.get("amount")),
        "amplitude": to_native_number(sanitized_item.get("amplitude")),
        "change_pct": to_native_number(sanitized_item.get("change_pct")),
        "change_amt": to_native_number(sanitized_item.get("change_amt")),
        "turnover": to_native_number(sanitized_item.get("turnover")),
        "is_realtime": bool(sanitized_item.get("is_realtime")),
        "date": to_native_text(sanitized_item.get("quote_date")),
        "refreshed_at": to_native_text(sanitized_item.get("refreshed_at")),
        "source": to_native_text(source) or source,
        "origin_source": stored_source,
    }


def merge_response_quotes(result: Dict[str, dict], quotes: Dict[str, dict], default_source: str) -> None:
    for code, item in quotes.items():
        result[code] = build_response(item, source=item.get("source") or default_source)


def empty_source_counts() -> dict:
    return {
        "efinance": 0,
        "cache": 0,
        "market_db_fallback": 0,
        "stale_cache": 0,
    }


def count_sources(quotes: Dict[str, dict]) -> dict:
    source_counts = empty_source_counts()
    for item in quotes.values():
        source = item.get("source")
        if source in source_counts:
            source_counts[source] += 1
    return source_counts


def build_meta(quotes: Dict[str, dict], refresh_context: dict, force_refresh: bool) -> dict:
    source_counts = count_sources(quotes)
    newest_quote_date = refresh_context.get("newest_quote_date")
    for item in quotes.values():
        quote_date = item.get("date")
        if quote_date and (newest_quote_date is None or quote_date > newest_quote_date):
            newest_quote_date = quote_date

    message = build_message(source_counts, refresh_context, newest_quote_date, force_refresh)
    return {
        "message": message,
        "today": refresh_context.get("today"),
        "is_trade_day": refresh_context.get("is_trade_day"),
        "market_closed": refresh_context.get("market_closed"),
        "latest_trade_date": refresh_context.get("latest_trade_date"),
        "newest_quote_date": newest_quote_date,
        "source_counts": source_counts,
    }


def build_message(
    source_counts: dict,
    refresh_context: dict,
    newest_quote_date: Optional[str],
    force_refresh: bool,
) -> str:
    if refresh_context.get("calendar_available") is False:
        if source_counts["efinance"] > 0:
            return "交易日历暂不可用，行情已刷新"
        return "交易日历暂不可用，当前显示缓存或最近收盘数据"

    is_trade_day = refresh_context.get("is_trade_day")
    market_closed = refresh_context.get("market_closed")
    latest_trade_date = refresh_context.get("latest_trade_date")

    if not is_trade_day:
        return "今天不是交易日，当前显示最近一个交易日收盘数据"

    if source_counts["efinance"] > 0:
        if market_closed and newest_quote_date and latest_trade_date and newest_quote_date >= latest_trade_date:
            return "今天已收盘，收盘数据已更新"
        return "行情刷新完成"

    if market_closed and latest_trade_date and newest_quote_date and newest_quote_date >= latest_trade_date:
        return "今天已收盘，当前数据已经是最新"

    if source_counts["cache"] > 0 and source_counts["market_db_fallback"] == 0 and source_counts["stale_cache"] == 0:
        return "行情已是 10 分钟内最新数据"

    if source_counts["market_db_fallback"] > 0 and source_counts["efinance"] == 0:
        return "当前显示最近一个交易日收盘数据"

    if source_counts["stale_cache"] > 0:
        return "刷新未成功，当前先显示最近一次缓存数据"

    if force_refresh:
        return "本次刷新未获取到新行情，请稍后再试"

    return "当前数据已更新"
