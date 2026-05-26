"""
统一行情刷新服务。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from config import settings
from core.market.quote_refresh_freshness import (
    is_quote_stale,
    summarize_cached_quotes,
)
from core.market.quote_refresh_payloads import (
    build_meta,
    build_quote_snapshot,
    build_response,
    count_sources,
    empty_source_counts,
    merge_response_quotes,
    sanitize_quotes_map,
    to_native_text,
)
from dao.market_dao import market_dao
from dao.quote_cache_dao import quote_cache_dao
from data_provider import efinance_adapter
from utils.date_utils import get_trade_day_close_context
from utils.logger import logger


class QuoteRefreshService:
    def __init__(
        self,
        cache_dao=quote_cache_dao,
        market_dao_inst=market_dao,
        efinance_adapter_inst=efinance_adapter,
        ttl_seconds: Optional[int] = None,
    ):
        self.cache_dao = cache_dao
        self.market_dao = market_dao_inst
        self.efinance_adapter = efinance_adapter_inst
        self.ttl_seconds = ttl_seconds or settings.EFINANCE_REFRESH_TTL_SECONDS

    def get_quotes(self, codes: List[str], force_refresh: bool = False) -> Dict[str, dict]:
        return self.get_quotes_payload(codes, force_refresh=force_refresh)["quotes"]

    def get_quotes_payload(self, codes: List[str], force_refresh: bool = False) -> Dict[str, dict]:
        normalized_codes = self._normalize_codes(codes)
        if not normalized_codes:
            return self._build_quotes_payload({}, force_refresh=force_refresh)

        cached_quotes = self._load_cached_quotes(normalized_codes)
        refresh_context = self._get_refresh_context(cached_quotes)
        stale_codes = self._resolve_stale_codes(
            normalized_codes,
            cached_quotes,
            refresh_context,
            force_refresh=force_refresh,
        )
        stale_code_set = set(stale_codes)

        result = self._build_cached_results(normalized_codes, cached_quotes, stale_code_set)
        unresolved_codes = list(stale_codes)
        unresolved_codes = self._refresh_quote_stage(
            unresolved_codes,
            cached_quotes,
            result,
            default_source="efinance",
            loader=self.refresh_quotes_from_efinance,
        )
        unresolved_codes = self._refresh_quote_stage(
            unresolved_codes,
            cached_quotes,
            result,
            default_source="efinance",
            loader=lambda missing: self.fill_from_efinance_history(missing, cached_quotes),
        )
        unresolved_codes = self._refresh_quote_stage(
            unresolved_codes,
            cached_quotes,
            result,
            default_source="market_db_fallback",
            loader=lambda missing: self.fill_from_market_db(missing, cached_quotes),
        )
        self._merge_stale_cache_quotes(result, unresolved_codes, cached_quotes)

        return self._build_quotes_payload(
            result,
            refresh_context=refresh_context,
            force_refresh=force_refresh,
        )

    def refresh_quotes_from_efinance(self, codes: List[str]) -> Dict[str, dict]:
        normalized_codes = self._normalize_codes(codes)
        if not normalized_codes:
            return {}

        now = self._now_text()
        quotes = self.efinance_adapter.fetch_realtime(normalized_codes) or {}
        result = {}
        for code, quote in quotes.items():
            result[code] = build_quote_snapshot(
                code=code,
                asset_name=getattr(quote, "name", None),
                quote_date=getattr(quote, "date", None),
                source="efinance",
                is_realtime=True,
                now=now,
                values={
                    "price": getattr(quote, "close", None),
                    "high": getattr(quote, "high", None),
                    "low": getattr(quote, "low", None),
                    "volume": getattr(quote, "volume", None),
                    "amount": getattr(quote, "amount", None),
                    "change_pct": getattr(quote, "change_pct", None),
                },
            )
        return result

    def fill_from_efinance_history(self, codes: List[str], cached_quotes: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
        normalized_codes = self._normalize_codes(codes)
        if not normalized_codes:
            return {}

        existing_quotes = cached_quotes or {}
        now = self._now_text()
        result: Dict[str, dict] = {}
        for code in normalized_codes:
            try:
                raw = self.efinance_adapter.fetch_raw(code, "", "")
                df = self.efinance_adapter.parse(raw)
                if df is None or df.empty:
                    continue
                last_row = df.iloc[-1]
                cached = existing_quotes.get(code, {})
                result[code] = build_quote_snapshot(
                    code=code,
                    asset_name=self._row_value(last_row, "name") or cached.get("asset_name") or code,
                    quote_date=str(self._row_value(last_row, "trade_date") or cached.get("quote_date") or "")[:10],
                    source="efinance",
                    is_realtime=False,
                    now=now,
                    cached=cached,
                    values={
                        "price": self._row_value(last_row, "close"),
                        "high": self._row_value(last_row, "high"),
                        "low": self._row_value(last_row, "low"),
                        "volume": self._row_value(last_row, "volume"),
                        "amount": self._row_value(last_row, "amount"),
                        "change_pct": self._row_value(last_row, "change_pct"),
                    },
                )
            except Exception:
                self._log_refresh_stage_failure("efinance_history", code=code)
        return result

    def fill_from_market_db(self, codes: List[str], cached_quotes: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
        normalized_codes = self._normalize_codes(codes)
        if not normalized_codes:
            return {}

        existing_quotes = cached_quotes or {}
        now = self._now_text()
        result: Dict[str, dict] = {}
        try:
            snapshots = self.market_dao.get_latest_prices_batch(normalized_codes)
            for code in normalized_codes:
                item = snapshots.get(code)
                if not item:
                    continue
                cached = existing_quotes.get(code, {})
                result[code] = build_quote_snapshot(
                    code=code,
                    asset_name=item.get("name") or cached.get("asset_name") or code,
                    quote_date=item.get("trade_date") or cached.get("quote_date"),
                    source="market_db_fallback",
                    is_realtime=False,
                    now=now,
                    cached=cached,
                    values={
                        "price": item.get("close"),
                        "high": item.get("high"),
                        "low": item.get("low"),
                        "volume": item.get("volume"),
                        "amount": item.get("amount"),
                    },
                )
        except Exception:
            self._log_refresh_stage_failure("market_db_fallback", codes=normalized_codes)
        return result

    def build_degraded_payload(self, codes: List[str]) -> Dict[str, dict]:
        normalized_codes = self._normalize_codes(codes)
        if not normalized_codes:
            return {
                "quotes": {},
                "meta": {
                    "message": "未提供有效代码",
                    "degraded": True,
                    "source_counts": empty_source_counts(),
                },
            }

        cached_quotes = self._load_cached_quotes(normalized_codes)
        result = self._build_stale_cache_results(normalized_codes, cached_quotes)
        unresolved_codes = [code for code in normalized_codes if code not in result]
        self._refresh_quote_stage(
            unresolved_codes,
            cached_quotes,
            result,
            default_source="market_db_fallback",
            loader=lambda missing: self.fill_from_market_db(missing, cached_quotes),
        )
        return {
            "quotes": result,
            "meta": {
                "message": "实时行情刷新异常，已降级为缓存或最近收盘数据",
                "degraded": True,
                "source_counts": count_sources(result),
            },
        }

    def _merge_response_quotes(self, result: Dict[str, dict], quotes: Dict[str, dict], default_source: str) -> None:
        merge_response_quotes(result, quotes, default_source=default_source)

    def _build_quotes_payload(
        self,
        quotes: Dict[str, dict],
        refresh_context: Optional[dict] = None,
        force_refresh: bool = False,
    ) -> Dict[str, dict]:
        context = refresh_context or self._get_refresh_context({})
        return {
            "quotes": quotes,
            "meta": build_meta(quotes, context, force_refresh=force_refresh),
        }

    def _load_cached_quotes(self, normalized_codes: List[str]) -> Dict[str, dict]:
        return sanitize_quotes_map(self.cache_dao.get_quotes_by_codes(normalized_codes))

    def _resolve_stale_codes(
        self,
        normalized_codes: List[str],
        cached_quotes: Dict[str, dict],
        refresh_context: dict,
        force_refresh: bool = False,
    ) -> List[str]:
        if force_refresh:
            return list(normalized_codes)
        now = datetime.now()
        market_close_hour = refresh_context.get("market_close_hour", settings.MARKET_CLOSE_HOUR)
        return [
            code
            for code in normalized_codes
            if is_quote_stale(
                cached_quotes.get(code),
                refresh_context,
                now,
                self.ttl_seconds,
                market_close_hour,
            )
        ]

    def _build_cached_results(
        self,
        normalized_codes: List[str],
        cached_quotes: Dict[str, dict],
        stale_code_set: set,
    ) -> Dict[str, dict]:
        result: Dict[str, dict] = {}
        for code in normalized_codes:
            cached = cached_quotes.get(code)
            if cached and code not in stale_code_set:
                result[code] = build_response(cached, source="cache")
        return result

    def _build_stale_cache_results(
        self,
        normalized_codes: List[str],
        cached_quotes: Dict[str, dict],
    ) -> Dict[str, dict]:
        result: Dict[str, dict] = {}
        self._merge_stale_cache_quotes(result, normalized_codes, cached_quotes)
        return result

    def _refresh_quote_stage(
        self,
        codes: List[str],
        cached_quotes: Dict[str, dict],
        result: Dict[str, dict],
        default_source: str,
        loader,
    ) -> List[str]:
        if not codes:
            return []

        refreshed_quotes = sanitize_quotes_map(loader(codes))
        if refreshed_quotes:
            self._persist_quotes(refreshed_quotes)
            self._merge_response_quotes(result, refreshed_quotes, default_source=default_source)
        return [code for code in codes if code not in refreshed_quotes]

    def _persist_quotes(self, quotes: Dict[str, dict]) -> None:
        if quotes:
            self.cache_dao.upsert_quotes(list(quotes.values()))

    def _merge_stale_cache_quotes(
        self,
        result: Dict[str, dict],
        codes: List[str],
        cached_quotes: Dict[str, dict],
    ) -> None:
        for code in codes:
            cached = cached_quotes.get(code)
            if cached:
                result[code] = build_response(cached, source="stale_cache")

    def _log_refresh_stage_failure(
        self,
        stage: str,
        codes: Optional[List[str]] = None,
        code: Optional[str] = None,
    ) -> None:
        if code is not None:
            logger.exception("[QUOTE_REFRESH][DEGRADE] stage=%s code=%s", stage, code)
            return
        code_text = ",".join(codes or [])
        logger.exception("[QUOTE_REFRESH][DEGRADE] stage=%s codes=%s", stage, code_text)

    def _normalize_codes(self, codes: List[str]) -> List[str]:
        seen = set()
        result = []
        for code in codes or []:
            normalized = (to_native_text(code) or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result[: settings.EFINANCE_MAX_CODES_PER_REQUEST]

    def _now_text(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _row_value(self, row, key: str):
        if row is None:
            return None
        getter = getattr(row, "get", None)
        if callable(getter):
            return getter(key)
        return None

    def _get_refresh_context(self, cached_quotes: Dict[str, dict]) -> dict:
        now = datetime.now()
        latest_trade_date = self.market_dao.get_latest_trade_date_global()
        market_context = get_trade_day_close_context(
            self.market_dao,
            settings.MARKET_CLOSE_HOUR,
            now=now,
        )
        cached_summary = summarize_cached_quotes(cached_quotes)

        return {
            **market_context,
            "latest_trade_date": latest_trade_date,
            **cached_summary,
        }


quote_refresh_service = QuoteRefreshService()
