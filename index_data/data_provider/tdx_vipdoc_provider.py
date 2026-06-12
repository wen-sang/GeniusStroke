from __future__ import annotations

import json
import msvcrt
import struct
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from config import settings
from config.constants import AssetType
from utils.validators import ValidationError


TDX_DAY_RECORD_SIZE = 32
TDX_MANIFEST_SCHEMA_VERSION = 1
TDX_SAMPLE_CODES = (
    ("SH", "000001"),
    ("SZ", "399001"),
    ("SZ", "399006"),
    ("SH", "510300"),
    ("SZ", "159915"),
)
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


class TdxPackageLockTimeout(TimeoutError):
    pass


class TdxVipdocProvider:
    def __init__(
        self,
        root: str | Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = Path(root or settings.TDX_VIPDOC_ROOT)
        self.clock = clock
        self.sleeper = sleeper

    @property
    def current_dir(self) -> Path:
        return self.root / "current"

    @property
    def manifest_path(self) -> Path:
        return self.current_dir / "manifest.json"

    @contextmanager
    def package_lock(
        self,
        timeout_seconds: float | None = None,
    ) -> Iterator[float]:
        timeout = (
            settings.TDX_GAP_FILL_LOCK_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        )
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".package.lock"
        started = self.clock()
        with lock_path.open("a+b") as lock_file:
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    elapsed = self.clock() - started
                    if elapsed >= timeout:
                        raise TdxPackageLockTimeout(
                            "TDX package lock wait timed out"
                        )
                    self.sleeper(min(0.1, max(0.0, timeout - elapsed)))
            try:
                yield self.clock() - started
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

    def read_manifest(self) -> dict:
        if not self.manifest_path.exists():
            raise ValidationError("TDX_MANIFEST_MISSING")
        try:
            manifest = json.loads(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("TDX_MANIFEST_INVALID") from exc
        if not isinstance(manifest, dict):
            raise ValidationError("TDX_MANIFEST_INVALID")
        return manifest

    def validate_gate(self, target_date: str) -> dict:
        try:
            manifest = self.read_manifest()
            self._validate_manifest(manifest, target_date)
            return {
                "status": "READY",
                "package_id": manifest["package_id"],
                "target_date": target_date,
                "max_trade_date": manifest["max_trade_date"],
                "skip_reason": None,
            }
        except ValidationError as exc:
            return {
                "status": "NOT_READY",
                "package_id": None,
                "target_date": target_date,
                "max_trade_date": None,
                "skip_reason": str(exc)[:200],
            }

    def read_asset_dates(
        self,
        exchange: str,
        asset_code: str,
        asset_type: str,
        target_dates: list[str],
    ) -> dict:
        file_path = find_tdx_day_file(
            self.current_dir,
            exchange,
            asset_code,
        )
        result = {
            "exchange": exchange,
            "asset_code": asset_code,
            "file_status": "ready",
            "file_error_code": None,
            "file_error_message": None,
            "date_results": {},
        }
        if file_path is None:
            result["file_status"] = "missing"
            result["file_error_code"] = "TDX_FILE_MISSING"
            return result
        try:
            bars = parse_tdx_day_file_for_dates(
                file_path=file_path,
                asset_code=asset_code,
                asset_type=asset_type,
                target_dates=set(target_dates),
            )
        except Exception as exc:
            result["file_status"] = "invalid"
            result["file_error_code"] = "TDX_FILE_INVALID"
            result["file_error_message"] = str(exc)[:200]
            return result

        for trade_date in target_dates:
            value = bars.get(trade_date)
            if isinstance(value, TdxDailyBar):
                if value.volume == 0 and value.amount == 0:
                    result["date_results"][trade_date] = {
                        "status": "zero",
                        "bar": None,
                    }
                else:
                    result["date_results"][trade_date] = {
                        "status": "hit",
                        "bar": value.to_market_row(),
                    }
            elif value == "invalid":
                result["date_results"][trade_date] = {
                    "status": "invalid",
                    "bar": None,
                }
            else:
                result["date_results"][trade_date] = {
                    "status": "empty",
                    "bar": None,
                }
        return result

    def _validate_manifest(self, manifest: dict, target_date: str) -> None:
        if manifest.get("schema_version") != TDX_MANIFEST_SCHEMA_VERSION:
            raise ValidationError("TDX_MANIFEST_SCHEMA_UNSUPPORTED")
        if manifest.get("validation_status") != "SUCCESS":
            raise ValidationError("TDX_MANIFEST_NOT_SUCCESS")
        if not manifest.get("package_id"):
            raise ValidationError("TDX_PACKAGE_ID_MISSING")

        counts = manifest.get("exchange_file_counts") or {}
        for exchange in ("SH", "SZ"):
            lday_dir = resolve_lday_dir(self.current_dir, exchange)
            if lday_dir is None:
                raise ValidationError(f"TDX_{exchange}_LDAY_MISSING")
            actual_count = sum(1 for _ in lday_dir.glob("*.day"))
            expected_count = int(counts.get(exchange) or 0)
            if actual_count != expected_count:
                raise ValidationError(f"TDX_{exchange}_FILE_COUNT_MISMATCH")
            if actual_count < settings.TDX_GAP_FILL_MIN_FILES_PER_EXCHANGE:
                raise ValidationError(f"TDX_{exchange}_FILE_COUNT_TOO_LOW")

        max_trade_date = manifest.get("max_trade_date")
        if not max_trade_date or max_trade_date < target_date:
            raise ValidationError("TDX_PACKAGE_DATE_BEHIND")
        samples = manifest.get("samples") or {}
        for exchange, asset_code in TDX_SAMPLE_CODES:
            key = f"{exchange.lower()}{asset_code}"
            if samples.get(key) != max_trade_date:
                raise ValidationError(f"TDX_SAMPLE_INVALID_{key.upper()}")
            file_path = find_tdx_day_file(
                self.current_dir,
                exchange,
                asset_code,
            )
            if not file_path or read_last_trade_date(file_path) != max_trade_date:
                raise ValidationError(f"TDX_SAMPLE_MISMATCH_{key.upper()}")


def build_manifest(
    package_dir: str | Path,
    package_id: str,
    page_update_date: str,
    resolved_zip_url: str,
    previous_manifest: dict | None = None,
) -> dict:
    root = Path(package_dir)
    counts = {}
    for exchange in ("SH", "SZ"):
        lday_dir = resolve_lday_dir(root, exchange)
        if lday_dir is None:
            raise ValidationError(f"TDX_{exchange}_LDAY_MISSING")
        count = sum(1 for _ in lday_dir.glob("*.day"))
        if count < settings.TDX_GAP_FILL_MIN_FILES_PER_EXCHANGE:
            raise ValidationError(f"TDX_{exchange}_FILE_COUNT_TOO_LOW")
        previous_count = int(
            ((previous_manifest or {}).get("exchange_file_counts") or {}).get(
                exchange
            )
            or 0
        )
        if (
            previous_count
            and count
            < previous_count * settings.TDX_GAP_FILL_MIN_PREVIOUS_FILE_RATIO
        ):
            raise ValidationError(f"TDX_{exchange}_FILE_COUNT_REGRESSION")
        counts[exchange] = count

    samples = {}
    sample_dates = []
    for exchange, asset_code in TDX_SAMPLE_CODES:
        file_path = find_tdx_day_file(root, exchange, asset_code)
        if file_path is None:
            raise ValidationError(
                f"TDX_SAMPLE_MISSING_{exchange}{asset_code}"
            )
        trade_date = read_last_trade_date(file_path)
        if not trade_date:
            raise ValidationError(
                f"TDX_SAMPLE_INVALID_{exchange}{asset_code}"
            )
        samples[f"{exchange.lower()}{asset_code}"] = trade_date
        sample_dates.append(trade_date)
    max_trade_date = max(sample_dates)
    if any(value != max_trade_date for value in sample_dates):
        raise ValidationError("TDX_SAMPLE_DATE_MISMATCH")

    return {
        "schema_version": TDX_MANIFEST_SCHEMA_VERSION,
        "package_id": package_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "page_update_date": page_update_date,
        "resolved_zip_url": resolved_zip_url,
        "max_trade_date": max_trade_date,
        "exchange_file_counts": counts,
        "samples": samples,
        "validation_status": "SUCCESS",
    }


def write_manifest(package_dir: str | Path, manifest: dict) -> None:
    path = Path(package_dir) / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def parse_tdx_day_file(
    file_path: str | Path,
    asset_code: str,
    asset_type: str,
) -> list[TdxDailyBar]:
    raw = Path(file_path).read_bytes()
    if len(raw) % TDX_DAY_RECORD_SIZE != 0:
        raise ValidationError(f"Invalid TDX day file size: {file_path}")
    scale = resolve_price_scale(asset_code, asset_type)
    return [
        _parse_tdx_day_record(
            raw[offset: offset + TDX_DAY_RECORD_SIZE],
            asset_code,
            scale,
        )
        for offset in range(0, len(raw), TDX_DAY_RECORD_SIZE)
    ]


def parse_tdx_day_file_for_dates(
    file_path: str | Path,
    asset_code: str,
    asset_type: str,
    target_dates: set[str],
) -> dict[str, TdxDailyBar | str]:
    raw = Path(file_path).read_bytes()
    if len(raw) % TDX_DAY_RECORD_SIZE != 0:
        raise ValidationError(f"Invalid TDX day file size: {file_path}")
    scale = resolve_price_scale(asset_code, asset_type)
    result: dict[str, TdxDailyBar | str] = {}
    for offset in range(0, len(raw), TDX_DAY_RECORD_SIZE):
        record = raw[offset: offset + TDX_DAY_RECORD_SIZE]
        raw_date = _RECORD_STRUCT.unpack(record)[0]
        trade_date = _format_tdx_date(raw_date)
        if trade_date not in target_dates:
            continue
        try:
            result[trade_date] = _parse_tdx_day_record(
                record,
                asset_code,
                scale,
            )
        except ValidationError:
            result[trade_date] = "invalid"
    return result


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
    value = parse_tdx_day_file_for_dates(
        file_path,
        asset_code,
        asset_type,
        {trade_date},
    ).get(trade_date)
    if value == "invalid":
        raise ValidationError("TDX target record is invalid")
    return value


def find_tdx_day_file(
    root: str | Path,
    exchange: str,
    asset_code: str,
) -> Path | None:
    lday_dir = resolve_lday_dir(Path(root), exchange)
    if lday_dir is None:
        return None
    prefix = exchange.lower()
    candidate = lday_dir / f"{prefix}{asset_code}.day"
    return candidate if candidate.is_file() else None


def resolve_lday_dir(root: Path, exchange: str) -> Path | None:
    prefix = exchange.lower()
    for candidate in (
        root / prefix / "lday",
        root / "vipdoc" / prefix / "lday",
    ):
        if candidate.is_dir():
            return candidate
    return None


def read_last_trade_date(file_path: str | Path) -> str | None:
    path = Path(file_path)
    try:
        with path.open("rb") as stream:
            stream.seek(-TDX_DAY_RECORD_SIZE, 2)
            record = stream.read(TDX_DAY_RECORD_SIZE)
    except (OSError, ValueError):
        return None
    if len(record) != TDX_DAY_RECORD_SIZE:
        return None
    return _format_tdx_date(_RECORD_STRUCT.unpack(record)[0])


def scan_max_trade_date(root: str | Path) -> str | None:
    dates = []
    root_path = Path(root)
    for exchange in ("SH", "SZ"):
        lday_dir = resolve_lday_dir(root_path, exchange)
        if lday_dir is None:
            continue
        for file_path in lday_dir.glob("*.day"):
            trade_date = read_last_trade_date(file_path)
            if trade_date:
                dates.append(trade_date)
    return max(dates) if dates else None


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
        if average_price < bar.low * 0.2 or average_price > bar.high * 5.0:
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


tdx_vipdoc_provider = TdxVipdocProvider()
