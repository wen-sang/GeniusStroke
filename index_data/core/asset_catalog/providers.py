from __future__ import annotations

import importlib
import re
from abc import ABC, abstractmethod
from typing import Any, Iterable

import requests

from config.constants import DataSource
from config.settings import (
    ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS,
    LIXINREN_TOKEN,
)


LIXINREN_CATALOG_ENDPOINTS = (
    ("cn_index", "大陆指数", "INDEX", "https://open.lixinger.com/api/cn/index"),
    ("cn_fund", "大陆基金", "FUND", "https://open.lixinger.com/api/cn/fund"),
    ("hk_index", "港股指数", "INDEX", "https://open.lixinger.com/api/hk/index"),
)


class BaseCatalogProvider(ABC):
    @abstractmethod
    def fetch_catalog_items(self) -> list[dict]:
        """返回统一的目录项字典列表。"""


class TickFlowCatalogProvider(BaseCatalogProvider):
    SUPPORTED_ASSET_TYPES = {"INDEX", "ETF", "STOCK"}

    def fetch_catalog_items(self) -> list[dict]:
        tickflow = importlib.import_module("tickflow")
        items = []
        for exchange in ("SH", "SZ", "HK"):
            raw_items = tickflow.exchanges.get_instruments(exchange)
            for raw in _iter_records(raw_items):
                mapped = self._map_record(raw, exchange)
                if mapped and mapped["asset_type"] in self.SUPPORTED_ASSET_TYPES:
                    items.append(mapped)
        return items

    def _map_record(self, raw: dict, fallback_exchange: str) -> dict | None:
        external_symbol = _first_value(
            raw,
            "symbol",
            "ticker",
            "instrument",
            "code",
        )
        if not external_symbol:
            return None
        external_symbol = str(external_symbol).strip()
        exchange = _normalize_exchange(
            _first_value(raw, "exchange", "market", "exchange_id") or fallback_exchange
        )
        asset_code = _strip_exchange_suffix(external_symbol)
        asset_name = _first_value(raw, "name", "display_name", "cn_name", "security_name")
        asset_type = _normalize_asset_type(
            _first_value(raw, "asset_type", "type", "instrument_type", "category")
        )
        if not asset_name:
            asset_name = asset_code
        return {
            "external_symbol": external_symbol,
            "asset_code": asset_code,
            "asset_name": str(asset_name).strip(),
            "asset_type": asset_type,
            "exchange": exchange,
            "market_category": "EXCHANGE",
            "listing_date": _normalize_date(_first_value(raw, "listing_date", "list_date")),
            "source_universe_id": fallback_exchange,
            "source_universe_name": f"TickFlow {fallback_exchange}",
            "source_asset_type": str(_first_value(raw, "asset_type", "type") or ""),
            "source_status": str(_first_value(raw, "status") or "active"),
            "raw_payload": raw,
        }


class LixinrenCatalogProvider(BaseCatalogProvider):
    def __init__(self, token: str | None = None):
        self.token = (token if token is not None else LIXINREN_TOKEN).strip()
        if not self.token:
            raise ValueError("LIXINREN_TOKEN 未配置，无法同步理杏仁目录")

    def fetch_catalog_items(self) -> list[dict]:
        items = []
        for universe_id, universe_name, default_asset_type, url in LIXINREN_CATALOG_ENDPOINTS:
            data = self._request(url)
            for raw in _iter_records(data):
                mapped = self._map_record(
                    raw=raw,
                    universe_id=universe_id,
                    universe_name=universe_name,
                    default_asset_type=default_asset_type,
                )
                if mapped:
                    items.append(mapped)
        return items

    def _request(self, url: str) -> Any:
        response = requests.post(
            url,
            json={"token": self.token},
            timeout=ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        code = str(payload.get("code"))
        if code not in {"0", "1", "200"}:
            raise RuntimeError(payload.get("message") or "理杏仁目录接口返回失败")
        return payload.get("data", [])

    def _map_record(
        self,
        raw: dict,
        universe_id: str,
        universe_name: str,
        default_asset_type: str,
    ) -> dict | None:
        code = _first_value(raw, "stockCode", "code", "fundCode", "indexCode")
        if not code:
            return None
        code = str(code).strip()
        name = _first_value(raw, "name", "stockName", "fundName", "indexName") or code
        source_exchange = _first_value(raw, "exchange", "market")
        asset_type = self._resolve_asset_type(raw, default_asset_type)
        exchange, market_category = self._resolve_exchange(code, source_exchange, asset_type)
        return {
            "external_symbol": code,
            "asset_code": code,
            "asset_name": str(name).strip(),
            "asset_type": asset_type,
            "exchange": exchange,
            "market_category": market_category,
            "listing_date": _normalize_date(_first_value(raw, "ipoDate", "listDate", "listingDate")),
            "source_universe_id": universe_id,
            "source_universe_name": universe_name,
            "source_asset_type": str(_first_value(raw, "type", "fundType", "category") or default_asset_type),
            "source_status": str(_first_value(raw, "status") or "active"),
            "raw_payload": raw,
        }

    @staticmethod
    def _resolve_asset_type(raw: dict, default_asset_type: str) -> str:
        raw_type = str(_first_value(raw, "type", "fundType", "category") or "").upper()
        if "ETF" in raw_type:
            return "ETF"
        return default_asset_type

    @staticmethod
    def _resolve_exchange(code: str, source_exchange: Any, asset_type: str) -> tuple[str | None, str]:
        exchange = _normalize_exchange(source_exchange)
        if exchange in {"SH", "SZ", "HK"}:
            return exchange, "EXCHANGE"
        if str(source_exchange).lower() == "jj" and asset_type != "ETF":
            return None, "OTC"
        inferred = _infer_cn_exchange(code)
        return inferred, "EXCHANGE" if inferred else "OTC"


def get_catalog_provider(source_id: str) -> BaseCatalogProvider:
    if source_id == DataSource.TICKFLOW:
        return TickFlowCatalogProvider()
    if source_id == DataSource.LIXINREN:
        return LixinrenCatalogProvider()
    raise ValueError(f"不支持的目录来源: {source_id}")


def _iter_records(raw_items: Any) -> Iterable[dict]:
    if raw_items is None:
        return []
    if hasattr(raw_items, "to_dict"):
        return raw_items.to_dict("records")
    if isinstance(raw_items, dict):
        for key in ("items", "list", "data"):
            value = raw_items.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return [raw_items]
    if isinstance(raw_items, list):
        return [x for x in raw_items if isinstance(x, dict)]
    return []


def _first_value(raw: dict, *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _strip_exchange_suffix(symbol: str) -> str:
    return str(symbol).split(".", 1)[0].strip()


def _normalize_exchange(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    mapping = {
        "SSE": "SH",
        "SHSE": "SH",
        "XSHG": "SH",
        "SH": "SH",
        "SZSE": "SZ",
        "XSHE": "SZ",
        "SZ": "SZ",
        "HKEX": "HK",
        "XHKG": "HK",
        "HK": "HK",
    }
    return mapping.get(text)


def _normalize_asset_type(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "ETF" in text:
        return "ETF"
    if "INDEX" in text or "IDX" in text:
        return "INDEX"
    if "STOCK" in text or "EQUITY" in text:
        return "STOCK"
    if "FUND" in text:
        return "FUND"
    return "STOCK"


def _normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    match = re.match(r"^(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    if not match:
        return None
    return "-".join(match.groups())


def _infer_cn_exchange(code: str) -> str | None:
    text = str(code).strip()
    if text.startswith(("5", "6", "9")):
        return "SH"
    if text.startswith(("0", "1", "2", "3")):
        return "SZ"
    return None
