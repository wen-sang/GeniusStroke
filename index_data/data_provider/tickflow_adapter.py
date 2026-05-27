import datetime
import importlib
import time
import threading
import re
from typing import Any

import pandas as pd

from config.settings import (
    TICKFLOW_ADJUST,
    TICKFLOW_API_KEY,
    TICKFLOW_KLINE_COUNT_LIMIT,
    TICKFLOW_MAX_RETRIES,
    TICKFLOW_TIMEOUT_SECONDS,
    TICKFLOW_REALTIME_REQUEST_SLEEP_SECONDS,
    TICKFLOW_REALTIME_MAX_CODES_PER_REQUEST,
)
from utils.exceptions import DataFetchError
from utils.validators import validate_asset_code, validate_date_range
from utils.logger import logger
from .base import BaseDataProvider

TICKFLOW_SYMBOL_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

class TickFlowRealtimeLimiter:
    def __init__(self, interval_seconds, clock=time.monotonic, sleeper=time.sleep):
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.sleeper = sleeper
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def wait_turn(self):
        with self._lock:
            now = self.clock()
            elapsed = now - self._last_request_at
            if elapsed < self.interval_seconds:
                sleep_time = self.interval_seconds - elapsed
                self.sleeper(sleep_time)
            self._last_request_at = self.clock()

tickflow_limiter = TickFlowRealtimeLimiter(TICKFLOW_REALTIME_REQUEST_SLEEP_SECONDS)


class TickFlowAdapter(BaseDataProvider):
    """TickFlow 日线采集适配器。"""

    def __init__(self, client: Any | None = None):
        self._client = client

    def fetch_realtime(
        self,
        symbol_items: list[dict],
    ) -> dict[str, dict]:
        """
        批量获取实时行情。
        输入项格式: {"asset_code": "...", "exchange": "...", "route_source_id": "...", "source_code": "..."}
        """
        if not symbol_items:
            return {}
            
        if not TICKFLOW_API_KEY:
            raise DataFetchError("TickFlow realtime requires TICKFLOW_API_KEY")

        symbols = []
        code_map = {}
        for item in symbol_items:
            asset_code = item["asset_code"]
            route_source_id = item.get("route_source_id")
            source_code = item.get("source_code")
            exchange = item.get("exchange")

            if route_source_id == "tickflow" and source_code and TICKFLOW_SYMBOL_PATTERN.match(source_code):
                symbol = source_code
            else:
                if not exchange:
                    continue
                symbol = f"{asset_code}.{exchange}"
            
            symbols.append(symbol)
            code_map[symbol] = asset_code

        if not symbols:
            return {}
            
        chunk_size = TICKFLOW_REALTIME_MAX_CODES_PER_REQUEST
        result = {}
        
        for i in range(0, len(symbols), chunk_size):
            chunk_symbols = symbols[i:i + chunk_size]
            tickflow_limiter.wait_turn()

            try:
                raw_data = self._get_client().quotes.get(
                    symbols=chunk_symbols,
                    as_dataframe=False
                )
            except Exception as exc:
                if self._is_rate_limit_error(exc):
                    raise DataFetchError(f"TickFlow rate limit while fetching realtime") from exc
                if self._is_timeout_error(exc):
                    raise DataFetchError(f"TickFlow timeout while fetching realtime") from exc
                if self._is_connection_error(exc):
                    raise DataFetchError(f"TickFlow connection error while fetching realtime") from exc
                if exc.__class__.__name__ in ("AuthenticationError", "PermissionError", "QuotaExhaustedError"):
                    logger.error(f"TickFlow auth/permission error: {exc}")
                    raise DataFetchError(f"TickFlow permission error") from exc
                raise DataFetchError(f"Failed to fetch realtime data from TickFlow") from exc

            if isinstance(raw_data, pd.DataFrame):
                items = [row.to_dict() for _, row in raw_data.iterrows()]
            else:
                items = raw_data if isinstance(raw_data, list) else (raw_data.values() if isinstance(raw_data, dict) else [])
            
            for q in items:
                sym = q.get("symbol")
                if not sym or sym not in code_map:
                    continue
                asset_code = code_map[sym]
                
                last_price = q.get("last_price")
                prev_close = q.get("prev_close")
                ext = q.get("ext", {}) if isinstance(q.get("ext"), dict) else {}
                
                change_pct = ext.get("change_pct") if ext else q.get("ext.change_pct")
                if change_pct is not None:
                    change_pct = change_pct * 100
                elif last_price is not None and prev_close and float(prev_close) > 0:
                    change_pct = (last_price - prev_close) / float(prev_close) * 100
                
                quote_date = q.get("trade_date") or q.get("date") or q.get("timestamp")
                if quote_date and isinstance(quote_date, (int, float)):
                    ts_val = float(quote_date)
                    if ts_val > 2e9:
                        ts_val /= 1000.0
                    quote_date = datetime.datetime.fromtimestamp(ts_val).strftime("%Y-%m-%d")
                
                asset_name = ext.get("name") if ext else q.get("ext.name")
                if not asset_name:
                    asset_name = q.get("name")
                
                result[asset_code] = {
                    "symbol": sym,
                    "price": last_price,
                    "high": q.get("high"),
                    "low": q.get("low"),
                    "volume": q.get("volume"),
                    "amount": q.get("amount"),
                    "asset_name": asset_name,
                    "change_pct": change_pct,
                    "quote_date": str(quote_date)[:10] if quote_date else None,
                }
        
        return result

    @staticmethod
    def build_symbol(
        asset_code: str,
        exchange: str | None = None,
        source_code: str | None = None,
    ) -> str:
        """优先使用路由 source_code，缺省时按内部代码和交易所拼接。"""
        if source_code:
            return source_code
        if not exchange:
            raise ValueError("TickFlow 采集需要 source_code 或 exchange")
        return f"{asset_code}.{exchange}"

    def fetch_raw(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> pd.DataFrame:
        validate_asset_code(asset_code)
        start_date, end_date = validate_date_range(start_date, end_date)
        symbol = self.build_symbol(
            asset_code=asset_code,
            exchange=kwargs.get("exchange"),
            source_code=kwargs.get("source_code"),
        )

        try:
            return self._get_client().klines.get(
                symbol,
                period="1d",
                start_time=self._to_epoch_ms(start_date),
                end_time=self._to_epoch_ms(end_date),
                count=TICKFLOW_KLINE_COUNT_LIMIT,
                adjust=TICKFLOW_ADJUST,
                as_dataframe=True,
            )
        except Exception as exc:
            if self._is_rate_limit_error(exc):
                raise DataFetchError(
                    f"TickFlow rate limit while fetching {asset_code}"
                ) from exc
            if self._is_timeout_error(exc):
                raise DataFetchError(
                    f"TickFlow timeout while fetching {asset_code}"
                ) from exc
            if self._is_connection_error(exc):
                raise DataFetchError(
                    f"TickFlow connection error while fetching {asset_code}"
                ) from exc
            raise DataFetchError(
                f"Failed to fetch data from TickFlow for {asset_code}"
            ) from exc

    def parse(self, raw_data: Any, **kwargs) -> pd.DataFrame:
        if raw_data is None:
            return pd.DataFrame()
        if isinstance(raw_data, pd.DataFrame):
            if raw_data.empty:
                return pd.DataFrame()
            df = raw_data.copy()
        else:
            if not raw_data:
                return pd.DataFrame()
            df = pd.DataFrame(raw_data)

        if "date" in df.columns and "trade_date" not in df.columns:
            df = df.rename(columns={"date": "trade_date"})
        if "trade_date" not in df.columns:
            return pd.DataFrame()

        df["trade_date"] = df["trade_date"].astype(str).str[:10]
        cols = ["trade_date", "open", "close", "high", "low", "volume", "amount"]
        for col in cols:
            if col not in df.columns:
                df[col] = None
        df = df[cols]

        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]
        return df

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

    @staticmethod
    def _to_epoch_ms(date_text: str) -> int:
        dt = datetime.datetime.strptime(date_text, "%Y-%m-%d")
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        return exc.__class__.__name__ == "RateLimitError"

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        return exc.__class__.__name__ == "TimeoutError"

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        return exc.__class__.__name__ == "ConnectionError"
