from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config.constants import AssetType, Exchange
from utils.validators import ValidationError


TDX_DAY_RECORD_SIZE = 32
_RECORD_STRUCT = struct.Struct("<iiiiifII")


@dataclass(frozen=True)
class TdxDailyBar:
    asset_code: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float

    def to_market_row(self, source_id: str = "tdx") -> dict:
        return {
            "asset_code": self.asset_code,
            "trade_date": self.trade_date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "source_id": source_id,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def parse_tdx_day_file(
    file_path: str | Path,
    asset_code: str,
    asset_type: str,
) -> list[TdxDailyBar]:
    path = Path(file_path)
    raw = path.read_bytes()
    if len(raw) % TDX_DAY_RECORD_SIZE != 0:
        raise ValidationError(f"Invalid TDX day file size: {path}")

    scale = resolve_price_scale(asset_code, asset_type)
    bars = []
    for offset in range(0, len(raw), TDX_DAY_RECORD_SIZE):
        record = raw[offset: offset + TDX_DAY_RECORD_SIZE]
        bars.append(_parse_tdx_day_record(record, asset_code, scale))
    return bars


def find_tdx_day_file(root: str | Path, exchange: str, asset_code: str) -> Path | None:
    prefix = _exchange_prefix(exchange)
    if prefix is None:
        return None

    root_path = Path(root)
    filename = f"{prefix}{asset_code}.day"
    candidates = [
        root_path / prefix / "lday" / filename,
        root_path / "vipdoc" / prefix / "lday" / filename,
        root_path / "lday" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for candidate in root_path.rglob(filename):
        if candidate.is_file():
            return candidate
    return None


def get_bar_for_date(
    root: str | Path,
    exchange: str,
    asset_code: str,
    asset_type: str,
    trade_date: str,
) -> TdxDailyBar | None:
    file_path = find_tdx_day_file(root, exchange, asset_code)
    if file_path is None:
        return None
    path = Path(file_path)
    raw = path.read_bytes()
    if len(raw) % TDX_DAY_RECORD_SIZE != 0:
        raise ValidationError(f"Invalid TDX day file size: {path}")

    scale = resolve_price_scale(asset_code, asset_type)
    for offset in range(0, len(raw), TDX_DAY_RECORD_SIZE):
        record = raw[offset: offset + TDX_DAY_RECORD_SIZE]
        raw_date = _RECORD_STRUCT.unpack(record)[0]
        if _format_tdx_date(raw_date) != trade_date:
            continue
        bar = _parse_tdx_day_record(record, asset_code, scale)
        if bar.trade_date == trade_date:
            return bar
    return None


def scan_max_trade_date(root: str | Path) -> str | None:
    root_path = Path(root)
    if not root_path.exists():
        return None

    max_trade_date = None
    for file_path in root_path.rglob("*.day"):
        try:
            raw = file_path.read_bytes()
        except OSError:
            continue
        if len(raw) < TDX_DAY_RECORD_SIZE:
            continue
        last_record = raw[-TDX_DAY_RECORD_SIZE:]
        try:
            raw_date = _RECORD_STRUCT.unpack(last_record)[0]
            trade_date = _format_tdx_date(raw_date)
        except Exception:
            continue
        if max_trade_date is None or trade_date > max_trade_date:
            max_trade_date = trade_date
    return max_trade_date


def resolve_price_scale(asset_code: str, asset_type: str) -> float:
    if asset_type in {AssetType.ETF, AssetType.LOF}:
        return 1000.0
    if asset_code.startswith(("15", "16", "50", "51", "52", "56", "58")):
        return 1000.0
    return 100.0


def validate_tdx_bar(bar: TdxDailyBar) -> None:
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        raise ValidationError("TDX OHLC prices must be positive")
    if bar.high < max(bar.open, bar.close, bar.low):
        raise ValidationError("TDX high price is invalid")
    if bar.low > min(bar.open, bar.close):
        raise ValidationError("TDX low price is invalid")
    if bar.volume < 0 or bar.amount < 0:
        raise ValidationError("TDX volume/amount must be non-negative")
    if bar.volume > 0 and bar.amount > 0:
        average_price = bar.amount / bar.volume
        if average_price <= 0:
            raise ValidationError("TDX average price is invalid")
        lower = bar.low * 0.2
        upper = bar.high * 5.0
        if average_price < lower or average_price > upper:
            raise ValidationError("TDX amount/volume price sanity check failed")


def _parse_tdx_day_record(
    record: bytes,
    asset_code: str,
    scale: float,
) -> TdxDailyBar:
    (
        raw_date,
        raw_open,
        raw_high,
        raw_low,
        raw_close,
        raw_amount,
        raw_volume,
        _reserved,
    ) = _RECORD_STRUCT.unpack(record)
    bar = TdxDailyBar(
        asset_code=asset_code,
        trade_date=_format_tdx_date(raw_date),
        open=raw_open / scale,
        high=raw_high / scale,
        low=raw_low / scale,
        close=raw_close / scale,
        volume=float(raw_volume),
        amount=float(raw_amount),
    )
    validate_tdx_bar(bar)
    return bar


def _format_tdx_date(raw_date: int) -> str:
    text = str(raw_date)
    if len(text) != 8:
        raise ValidationError(f"Invalid TDX date: {raw_date}")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _exchange_prefix(exchange: str) -> str | None:
    if exchange == Exchange.SH:
        return "sh"
    if exchange == Exchange.SZ:
        return "sz"
    return None
