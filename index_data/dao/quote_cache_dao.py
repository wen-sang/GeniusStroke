"""
实时行情缓存 DAO。
"""
import sqlite3
import struct
from typing import Dict, List

from dao.base_dao import BaseDAO


class QuoteCacheDAO(BaseDAO):
    _TEXT_FIELDS = {"asset_code", "asset_name", "quote_date", "source", "refreshed_at", "updated_at", "created_at"}
    _NUMERIC_FIELDS = {"price", "high", "low", "volume", "amount", "amplitude", "change_pct", "change_amt", "turnover"}

    @property
    def table_name(self) -> str:
        return "dat_realtime_quote_cache"

    def get_quotes_by_codes(self, asset_codes: List[str]) -> Dict[str, dict]:
        if not asset_codes:
            return {}

        placeholders = ",".join("?" * len(asset_codes))
        sql = f"""
        SELECT
            asset_code,
            asset_name,
            price,
            high,
            low,
            volume,
            amount,
            amplitude,
            change_pct,
            change_amt,
            turnover,
            quote_date,
            source,
            is_realtime,
            refreshed_at,
            updated_at
        FROM dat_realtime_quote_cache
        WHERE asset_code IN ({placeholders})
        """

        try:
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, tuple(asset_codes))
                rows = self._rows_to_dicts(cursor, cursor.fetchall())
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            self._ensure_table()
            with self.db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, tuple(asset_codes))
                rows = self._rows_to_dicts(cursor, cursor.fetchall())

        sanitized_rows = [self._sanitize_row(row) for row in rows]
        return {
            row["asset_code"]: row
            for row in sanitized_rows
            if row.get("asset_code")
        }

    def upsert_quotes(self, quotes: List[dict]) -> int:
        if not quotes:
            return 0

        sql = """
        INSERT INTO dat_realtime_quote_cache (
            asset_code,
            asset_name,
            price,
            high,
            low,
            volume,
            amount,
            amplitude,
            change_pct,
            change_amt,
            turnover,
            quote_date,
            source,
            is_realtime,
            refreshed_at,
            updated_at,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_code) DO UPDATE SET
            asset_name=excluded.asset_name,
            price=excluded.price,
            high=excluded.high,
            low=excluded.low,
            volume=excluded.volume,
            amount=excluded.amount,
            amplitude=excluded.amplitude,
            change_pct=excluded.change_pct,
            change_amt=excluded.change_amt,
            turnover=excluded.turnover,
            quote_date=excluded.quote_date,
            source=excluded.source,
            is_realtime=excluded.is_realtime,
            refreshed_at=excluded.refreshed_at,
            updated_at=excluded.updated_at
        """

        rows = [
            (
                self._normalize_text(item.get("asset_code")),
                self._normalize_text(item.get("asset_name")),
                self._normalize_number(item.get("price")),
                self._normalize_number(item.get("high")),
                self._normalize_number(item.get("low")),
                self._normalize_number(item.get("volume")),
                self._normalize_number(item.get("amount")),
                self._normalize_number(item.get("amplitude")),
                self._normalize_number(item.get("change_pct")),
                self._normalize_number(item.get("change_amt")),
                self._normalize_number(item.get("turnover")),
                self._normalize_text(item.get("quote_date")),
                self._normalize_text(item.get("source")),
                1 if item.get("is_realtime") else 0,
                self._normalize_text(item.get("refreshed_at")),
                self._normalize_text(item.get("updated_at")),
                self._normalize_text(item.get("created_at")),
            )
            for item in quotes
            if item.get("asset_code")
        ]
        try:
            return self._execute_many(sql, rows)
        except Exception as exc:
            if "no such table" not in str(exc).lower():
                raise
            self._ensure_table()
            return self._execute_many(sql, rows)

    def _ensure_table(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS dat_realtime_quote_cache (
            asset_code TEXT PRIMARY KEY,
            asset_name TEXT,
            price REAL,
            high REAL,
            low REAL,
            volume REAL,
            amount REAL,
            amplitude REAL,
            change_pct REAL,
            change_amt REAL,
            turnover REAL,
            quote_date TEXT,
            source TEXT,
            is_realtime INTEGER DEFAULT 0,
            refreshed_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_quote_cache_refreshed_at
        ON dat_realtime_quote_cache(refreshed_at);
        """
        self.db_engine.execute_script(sql)

    def _sanitize_row(self, row: dict) -> dict:
        sanitized = dict(row)
        for field in self._TEXT_FIELDS:
            if field in sanitized:
                sanitized[field] = self._normalize_text(sanitized.get(field))
        for field in self._NUMERIC_FIELDS:
            if field in sanitized:
                sanitized[field] = self._normalize_number(sanitized.get(field))
        return sanitized

    def _normalize_text(self, value):
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

    def _normalize_number(self, value):
        if value is None:
            return None
        if hasattr(value, "item"):
            try:
                value = value.item()
            except Exception:
                pass
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, bytes):
            if len(value) == 8:
                try:
                    as_int = struct.unpack("<q", value)[0]
                    return as_int
                except struct.error:
                    pass
                try:
                    as_float = struct.unpack("<d", value)[0]
                    if as_float == as_float:
                        return as_float
                except struct.error:
                    pass
            try:
                return float(value.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


quote_cache_dao = QuoteCacheDAO()
