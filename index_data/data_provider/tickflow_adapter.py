import datetime
import importlib
from typing import Any

import pandas as pd

from config.settings import (
    TICKFLOW_ADJUST,
    TICKFLOW_API_KEY,
    TICKFLOW_KLINE_COUNT_LIMIT,
    TICKFLOW_MAX_RETRIES,
    TICKFLOW_TIMEOUT_SECONDS,
)
from utils.exceptions import DataFetchError
from utils.validators import validate_asset_code, validate_date_range
from .base import BaseDataProvider


class TickFlowAdapter(BaseDataProvider):
    """TickFlow 日线采集适配器。"""

    def __init__(self, client: Any | None = None):
        self._client = client

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
