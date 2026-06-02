from __future__ import annotations

import importlib
import re
from datetime import date
from abc import ABC, abstractmethod
from typing import Any, Iterable

import requests

from config.constants import DataSource
from config.settings import (
    ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS,
    LIXINREN_TOKEN,
    TICKFLOW_API_KEY,
    TICKFLOW_MAX_RETRIES,
    TICKFLOW_TIMEOUT_SECONDS,
)


LIXINREN_CATALOG_ENDPOINTS = (
    (
        "cn_index",
        "大陆指数",
        "INDEX",
        "https://open.lixinger.com/api/cn/index",
        False,
    ),
    (
        "cn_fund",
        "大陆基金",
        "FUND",
        "https://open.lixinger.com/api/cn/fund",
        True,
    ),
    (
        "cn_company",
        "大陆股票",
        "STOCK",
        "https://open.lixinger.com/api/cn/company",
        True,
    ),
    (
        "hk_index",
        "港股指数",
        "INDEX",
        "https://open.lixinger.com/api/hk/index",
        False,
    ),
)

LIXINREN_CATALOG_REQUEST_MAX_ATTEMPTS = 3


class BaseCatalogProvider(ABC):
    @abstractmethod
    def fetch_catalog_items(self) -> list[dict]:
        """返回统一的目录项字典列表。"""


class TickFlowCatalogProvider(BaseCatalogProvider):
    SUPPORTED_ASSET_TYPES = {"INDEX", "ETF", "STOCK"}

    def __init__(self, client: Any | None = None):
        self._client = client

    def fetch_catalog_items(self) -> list[dict]:
        items = []
        try:
            for exchange in ("SH", "SZ", "BJ", "HK"):
                raw_items = self._get_client().exchanges.get_instruments(exchange)
                for raw in _iter_records(raw_items):
                    mapped = self._map_record(raw, exchange)
                    if mapped and mapped["asset_type"] in self.SUPPORTED_ASSET_TYPES:
                        items.append(mapped)
        finally:
            self.close()
        return items

    def _get_client(self) -> Any:
        if self._client is None:
            tickflow = importlib.import_module("tickflow")
            tickflow_cls = getattr(tickflow, "TickFlow")
            client_kwargs = {
                "timeout": TICKFLOW_TIMEOUT_SECONDS,
                "max_retries": TICKFLOW_MAX_RETRIES,
            }
            if TICKFLOW_API_KEY:
                self._client = tickflow_cls(
                    api_key=TICKFLOW_API_KEY,
                    **client_kwargs,
                )
            else:
                try:
                    self._client = tickflow_cls.free(**client_kwargs)
                except TypeError:
                    self._client = tickflow_cls.free()
        return self._client

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()
        self._client = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

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
        asset_name = _first_value(
            raw,
            "name",
            "display_name",
            "cn_name",
            "security_name",
        )
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
            "listing_date": _normalize_date(
                _first_value(
                    raw,
                    "listing_date",
                    "list_date",
                    "ext.listing_date",
                    "ext.list_date",
                )
            ),
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
        for (
            universe_id,
            universe_name,
            default_asset_type,
            url,
            paginated,
        ) in LIXINREN_CATALOG_ENDPOINTS:
            for raw in self._fetch_records(
                url,
                paginated,
                page_index_start=0 if universe_id == "cn_company" else 1,
            ):
                mapped = self._map_record(
                    raw=raw,
                    universe_id=universe_id,
                    universe_name=universe_name,
                    default_asset_type=default_asset_type,
                )
                if mapped:
                    items.append(mapped)
        return items

    def _fetch_records(
        self,
        url: str,
        paginated: bool,
        page_index_start: int = 1,
    ) -> Iterable[dict]:
        if not paginated:
            return _iter_records(self._request(url))

        records = []
        total = None
        for page_index in range(page_index_start, 1001):
            payload = self._request_payload(url, {"pageIndex": page_index})
            if total is None:
                total = _normalize_int(payload.get("total"))
            page_records = list(_iter_records(payload.get("data", [])))
            if not page_records:
                break
            records.extend(page_records)
            if total is not None and len(records) >= total:
                break
        return records

    def _request(self, url: str, extra_payload: dict | None = None) -> Any:
        return self._request_payload(url, extra_payload).get("data", [])

    def _request_payload(self, url: str, extra_payload: dict | None = None) -> dict:
        payload = {"token": self.token}
        if extra_payload:
            payload.update(extra_payload)
        for attempt in range(1, LIXINREN_CATALOG_REQUEST_MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    timeout=ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS,
                )
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt == LIXINREN_CATALOG_REQUEST_MAX_ATTEMPTS:
                    raise
        response.raise_for_status()
        payload = response.json()
        code = str(payload.get("code"))
        if code not in {"0", "1", "200"}:
            raise RuntimeError(payload.get("message") or "理杏仁目录接口返回失败")
        return payload

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
        if universe_id == "cn_company" and not self._is_supported_company(raw):
            return None
        name = self._resolve_name(raw, universe_id) or code
        source_exchange = _first_value(raw, "exchange", "market")
        asset_type = self._resolve_asset_type(raw, default_asset_type)
        exchange, market_category = self._resolve_exchange(
            code,
            source_exchange,
            asset_type,
            universe_id,
        )
        if universe_id == "cn_company" and asset_type == "STOCK":
            if str(source_exchange or "").strip().lower() == "bj":
                return None
        return {
            "external_symbol": f"{universe_id}:{code}",
            "asset_code": code,
            "asset_name": str(name).strip(),
            "asset_type": asset_type,
            "exchange": exchange,
            "market_category": market_category,
            "listing_date": self._resolve_listing_date(raw, universe_id),
            "source_universe_id": universe_id,
            "source_universe_name": universe_name,
            "source_asset_type": str(_first_value(
                raw,
                "fundSecondLevel",
                "type",
                "fundType",
                "category",
            ) or default_asset_type),
            "source_status": str(
                _first_value(raw, "listingStatus", "status") or "active"
            ),
            "raw_payload": raw,
        }

    @staticmethod
    def _is_supported_company(raw: dict) -> bool:
        status = _first_value(raw, "listingStatus")
        if status is None:
            ipo_date = _normalize_date(_first_value(raw, "ipoDate"))
            return bool(ipo_date and ipo_date <= date.today().isoformat())
        normalized = str(status).strip().lower()
        return normalized in {
            "active",
            "listed",
            "listing",
            "normal",
            "上市",
            "正常",
            "正常上市",
        }

    @staticmethod
    def _resolve_name(raw: dict, universe_id: str) -> Any:
        if universe_id == "cn_fund":
            return _first_value(raw, "shortName", "name")
        return _first_value(raw, "name", "stockName", "fundName", "indexName")

    @staticmethod
    def _resolve_listing_date(raw: dict, universe_id: str) -> str | None:
        if universe_id == "cn_fund":
            return _normalize_date(_first_value(raw, "inceptionDate"))
        if universe_id == "cn_company":
            return _normalize_date(_first_value(raw, "ipoDate"))
        return _normalize_date(_first_value(raw, "launchDate"))

    @staticmethod
    def _resolve_asset_type(raw: dict, default_asset_type: str) -> str:
        raw_type = str(_first_value(
            raw,
            "fundSecondLevel",
            "type",
            "fundType",
            "category",
        ) or "").upper()
        if "ETF" in raw_type:
            return "ETF"
        return default_asset_type

    @staticmethod
    def _resolve_exchange(
        code: str,
        source_exchange: Any,
        asset_type: str,
        universe_id: str,
    ) -> tuple[str | None, str]:
        if universe_id == "hk_index":
            return "HK", "EXCHANGE"
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
        records = []
        for item in raw_items:
            record = _to_record(item)
            if record:
                records.append(record)
        return records
    record = _to_record(raw_items)
    if record:
        return [record]
    return []


def _to_record(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return None


def _first_value(raw: dict, *keys: str) -> Any:
    for key in keys:
        value = _get_nested_value(raw, key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _get_nested_value(raw: dict, key: str) -> Any:
    value = raw
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


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


def _normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _infer_cn_exchange(code: str) -> str | None:
    text = str(code).strip()
    if text.startswith(("5", "6", "9")):
        return "SH"
    if text.startswith(("0", "1", "2", "3")):
        return "SZ"
    return None
