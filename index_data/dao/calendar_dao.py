from __future__ import annotations

from datetime import datetime
from typing import Any

from config.constants import Exchange
from dao.base_dao import BaseDAO


class CalendarDAO(BaseDAO):
    """DAO for the multi-exchange natural-day trading calendar."""

    @property
    def table_name(self) -> str:
        return "trade_calendar_exchange"

    def replace_exchange_calendar(self, rows: list[dict]) -> None:
        data = self._validate_calendar_rows(rows)

        with self.db_engine.get_connection(readonly=False) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trade_calendar_exchange")
            cursor.executemany(
                """
                INSERT INTO trade_calendar_exchange
                    (exchange, calendar_date, is_open, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                data,
            )

    def get_calendar_coverage(self) -> list[dict]:
        sql = """
        SELECT
            exchange,
            MIN(calendar_date) AS coverage_start,
            MAX(calendar_date) AS coverage_end,
            COUNT(*) AS total_days,
            SUM(is_open) AS open_days,
            SUM(CASE WHEN is_open = 0 THEN 1 ELSE 0 END) AS closed_days
        FROM trade_calendar_exchange
        GROUP BY exchange
        ORDER BY exchange
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def get_exchange_date_bounds(self, exchange: str) -> dict:
        normalized_exchange = self._validate_exchange(exchange)
        sql = """
        SELECT
            exchange,
            MIN(calendar_date) AS coverage_start,
            MAX(calendar_date) AS coverage_end,
            COUNT(*) AS total_days,
            SUM(is_open) AS open_days,
            SUM(CASE WHEN is_open = 0 THEN 1 ELSE 0 END) AS closed_days,
            SUM(CASE WHEN is_open NOT IN (0, 1) OR is_open IS NULL
                THEN 1 ELSE 0 END) AS invalid_is_open_days
        FROM trade_calendar_exchange
        WHERE exchange = ?
        GROUP BY exchange
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (normalized_exchange,))
            return self._row_to_dict(cursor, cursor.fetchone())

    def validate_exchange_calendar_integrity(
        self,
        expected_start_dates: dict[str, str],
        required_end: str | None = None,
    ) -> dict:
        expected_exchanges = set(Exchange.VALID)
        coverage = {
            row["exchange"]: row
            for row in self.get_calendar_coverage()
        }
        issues = []

        actual_exchanges = set(coverage)
        missing_exchanges = expected_exchanges - actual_exchanges
        invalid_exchanges = actual_exchanges - expected_exchanges
        if missing_exchanges:
            issues.append(
                "missing exchanges: " + ", ".join(sorted(missing_exchanges))
            )
        if invalid_exchanges:
            issues.append(
                "invalid exchanges: " + ", ".join(sorted(invalid_exchanges))
            )

        exchange_bounds = {}
        for exchange in Exchange.VALID:
            bounds = self.get_exchange_date_bounds(exchange)
            exchange_bounds[exchange] = bounds
            if not bounds:
                continue

            expected_start = expected_start_dates.get(exchange)
            if expected_start and bounds["coverage_start"] != expected_start:
                issues.append(
                    f"{exchange} coverage_start {bounds['coverage_start']} "
                    f"!= expected {expected_start}"
                )

            if required_end and bounds["coverage_end"] < required_end:
                issues.append(
                    f"{exchange} coverage_end {bounds['coverage_end']} "
                    f"< required {required_end}"
                )

            invalid_is_open_days = int(bounds.get("invalid_is_open_days") or 0)
            if invalid_is_open_days:
                issues.append(
                    f"{exchange} has invalid is_open rows: "
                    f"{invalid_is_open_days}"
                )

            expected_days = self._inclusive_day_count(
                bounds["coverage_start"],
                bounds["coverage_end"],
            )
            if int(bounds["total_days"]) != expected_days:
                issues.append(
                    f"{exchange} natural-day coverage is not continuous: "
                    f"rows={bounds['total_days']} expected={expected_days}"
                )

        coverage_ends = {
            bounds["coverage_end"]
            for bounds in exchange_bounds.values()
            if bounds
        }
        if len(coverage_ends) > 1:
            issues.append(
                "exchange coverage_end values differ: "
                + ", ".join(sorted(coverage_ends))
            )

        return {
            "valid": not issues,
            "issues": issues,
            "coverage": list(coverage.values()),
            "exchange_bounds": exchange_bounds,
        }

    def get_open_dates(
        self,
        exchange: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[str]:
        normalized_exchange = self._validate_exchange(exchange)
        conditions = ["exchange = ?", "is_open = 1"]
        params: list[Any] = [normalized_exchange]

        if start_date:
            conditions.append("calendar_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("calendar_date <= ?")
            params.append(end_date)

        sql = f"""
        SELECT calendar_date
        FROM trade_calendar_exchange
        WHERE {' AND '.join(conditions)}
        ORDER BY calendar_date
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return [row[0] for row in cursor.fetchall()]

    def is_open_date(self, exchange: str, calendar_date: str) -> bool:
        normalized_exchange = self._validate_exchange(exchange)
        sql = """
        SELECT is_open
        FROM trade_calendar_exchange
        WHERE exchange = ? AND calendar_date = ?
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (normalized_exchange, calendar_date))
            row = cursor.fetchone()
            return bool(row and row[0] == 1)

    def _validate_calendar_rows(self, rows: list[dict]) -> list[tuple]:
        if not rows:
            raise ValueError("exchange calendar rows must not be empty")

        expected_exchanges = set(Exchange.VALID)
        row_exchanges = {
            self._normalize_exchange(row.get("exchange"))
            for row in rows
        }
        invalid_exchanges = row_exchanges - expected_exchanges
        if invalid_exchanges:
            values = ", ".join(sorted(invalid_exchanges))
            raise ValueError(f"invalid exchange calendar exchange: {values}")

        missing_exchanges = expected_exchanges - row_exchanges
        if missing_exchanges:
            values = ", ".join(sorted(missing_exchanges))
            raise ValueError(f"missing exchange calendar exchange: {values}")

        data = []
        for row in rows:
            exchange = self._normalize_exchange(row.get("exchange"))
            is_open = row.get("is_open")
            if is_open not in (0, 1):
                raise ValueError("exchange calendar is_open must be 0 or 1")
            data.append(
                (
                    exchange,
                    row.get("calendar_date"),
                    int(is_open),
                    row.get("updated_at"),
                )
            )
        return data

    def _validate_exchange(self, exchange: str) -> str:
        normalized_exchange = self._normalize_exchange(exchange)
        if normalized_exchange not in set(Exchange.VALID):
            raise ValueError(
                f"invalid exchange: {exchange}. expected one of: "
                f"{', '.join(Exchange.VALID)}"
            )
        return normalized_exchange

    @staticmethod
    def _normalize_exchange(exchange: Any) -> str:
        return str(exchange or "").strip().upper()

    @staticmethod
    def _inclusive_day_count(start_date: str, end_date: str) -> int:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        return (end - start).days + 1


calendar_dao = CalendarDAO()
