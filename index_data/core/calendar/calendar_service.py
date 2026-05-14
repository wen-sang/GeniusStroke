from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from config.constants import Exchange
from dao.calendar_dao import calendar_dao
from dao.market_dao import market_dao
from data_provider.exchange_calendar_provider import ExchangeCalendarProvider
from data_provider.exchange_calendar_provider import EXCHANGE_START_DATES
from utils.date_utils import get_current_date
from utils.logger import logger


CALENDAR_COVERAGE_THRESHOLD_DAYS = 90
LEGACY_CALENDAR_EXCHANGE = Exchange.SH


class CalendarCoverageError(RuntimeError):
    """Raised when calendar coverage is insufficient for production use."""


class CalendarService:
    """Service entry point for the new exchange calendar data product."""

    def __init__(
        self,
        provider: ExchangeCalendarProvider | None = None,
        dao=None,
        legacy_dao=None,
        coverage_threshold_days: int = CALENDAR_COVERAGE_THRESHOLD_DAYS,
    ):
        self.provider = provider or ExchangeCalendarProvider()
        self.dao = dao or calendar_dao
        self.legacy_dao = legacy_dao or market_dao
        self.coverage_threshold_days = coverage_threshold_days

    def refresh_exchange_calendar(self) -> dict:
        rows = self.provider.build_exchange_calendars()
        summary = self._build_summary(rows)
        self.dao.replace_exchange_calendar(rows)
        logger.info(
            "[TRADE_CALENDAR] refreshed trade_calendar_exchange rows=%s",
            len(rows),
        )
        return summary

    def ensure_calendar_coverage(
        self,
        required_end: str | None = None,
        current_date: str | None = None,
    ) -> dict:
        current_date = current_date or get_current_date()
        provider_end = self.provider.default_end()
        minimum_end = self._minimum_required_end(
            current_date=current_date,
            required_end=required_end,
        )
        if provider_end < minimum_end:
            raise CalendarCoverageError(
                f"exchange-calendars default_end {provider_end} "
                f"is before required end {minimum_end}"
            )

        validation = self._validate_exchange_calendar(provider_end)
        if not validation["valid"]:
            logger.warning(
                "[TRADE_CALENDAR] exchange calendar invalid, refreshing: %s",
                "; ".join(validation["issues"]),
            )
            self.refresh_exchange_calendar()
            validation = self._validate_exchange_calendar(provider_end)

        if not validation["valid"]:
            raise CalendarCoverageError(
                "trade_calendar_exchange validation failed: "
                + "; ".join(validation["issues"])
            )

        coverage_end = self._minimum_exchange_coverage_end(validation)
        if self._is_coverage_insufficient(coverage_end, current_date):
            raise CalendarCoverageError(
                f"trade_calendar_exchange coverage_end {coverage_end} "
                f"is insufficient for current date {current_date}"
            )

        return {
            "exchange_calendars_version": self.provider.library_version(),
            "provider_default_end": provider_end,
            "required_end": minimum_end,
            "coverage_end": coverage_end,
            "validation": validation,
        }

    def sync_legacy_trade_calendar(
        self,
        required_end: str | None = None,
        current_date: str | None = None,
    ) -> dict:
        coverage_summary = self.ensure_calendar_coverage(
            required_end=required_end,
            current_date=current_date,
        )
        current_date = current_date or get_current_date()
        sh_open_dates = self.dao.get_open_dates(LEGACY_CALENDAR_EXCHANGE)
        if not sh_open_dates:
            raise CalendarCoverageError("SH open-date projection is empty")

        old_dates = self.legacy_dao.get_trade_calendar()
        changed = old_dates != sh_open_dates
        if changed:
            self.legacy_dao.update_calendar(sh_open_dates)

        validation = self.validate_legacy_projection()
        if validation["difference_count"]:
            raise CalendarCoverageError(
                "legacy trade_calendar does not match SH projection"
            )

        legacy_end = validation["legacy_end"]
        if self._is_coverage_insufficient(legacy_end, current_date):
            raise CalendarCoverageError(
                f"legacy trade_calendar coverage_end {legacy_end} "
                f"is insufficient for current date {current_date}"
            )

        logger.info(
            "[TRADE_CALENDAR] legacy trade_calendar synced changed=%s "
            "rows=%s coverage_end=%s",
            changed,
            validation["legacy_count"],
            legacy_end,
        )
        return {
            "changed": changed,
            "legacy_count": validation["legacy_count"],
            "projection_count": validation["projection_count"],
            "legacy_start": validation["legacy_start"],
            "legacy_end": legacy_end,
            "coverage": coverage_summary,
            "validation": validation,
        }

    def validate_legacy_projection(self) -> dict:
        projection = self.dao.get_open_dates(LEGACY_CALENDAR_EXCHANGE)
        legacy_dates = self.legacy_dao.get_trade_calendar()
        projection_set = set(projection)
        legacy_set = set(legacy_dates)

        missing_dates = [
            date for date in projection if date not in legacy_set
        ]
        extra_dates = [
            date for date in legacy_dates if date not in projection_set
        ]
        return {
            "legacy_count": len(legacy_dates),
            "projection_count": len(projection),
            "legacy_start": legacy_dates[0] if legacy_dates else None,
            "legacy_end": legacy_dates[-1] if legacy_dates else None,
            "projection_start": projection[0] if projection else None,
            "projection_end": projection[-1] if projection else None,
            "difference_count": len(missing_dates) + len(extra_dates),
            "missing_dates": missing_dates[:20],
            "extra_dates": extra_dates[:20],
        }

    def calendar_status(self, current_date: str | None = None) -> dict:
        current_date = current_date or get_current_date()
        provider_end = self.provider.default_end()
        minimum_end = self._minimum_required_end(current_date)
        validation = self.dao.validate_exchange_calendar_integrity(
            EXCHANGE_START_DATES,
        )
        legacy_validation = self.validate_legacy_projection()
        exchange_end = self._minimum_exchange_coverage_end(validation)
        legacy_end = legacy_validation["legacy_end"]
        hard_failure = (
            provider_end < minimum_end
            or not validation["valid"]
            or self._is_coverage_insufficient(exchange_end, current_date)
            or self._is_coverage_insufficient(legacy_end, current_date)
            or legacy_validation["difference_count"] > 0
        )

        return {
            "exchange_calendars_version": self.provider.library_version(),
            "provider_default_end": provider_end,
            "current_date": current_date,
            "required_end": minimum_end,
            "exchange_coverage": validation["coverage"],
            "exchange_issues": validation["issues"],
            "legacy_projection": legacy_validation,
            "days_until_exchange_coverage_end": self._days_until(
                exchange_end,
                current_date,
            ),
            "days_until_legacy_coverage_end": self._days_until(
                legacy_end,
                current_date,
            ),
            "hard_failure": hard_failure,
        }

    def annual_refresh(
        self,
        required_end: str,
        current_date: str | None = None,
    ) -> dict:
        provider_end = self.provider.default_end()
        if provider_end < required_end:
            raise CalendarCoverageError(
                f"exchange-calendars default_end {provider_end} "
                f"is before required_end {required_end}"
            )

        exchange_summary = self.refresh_exchange_calendar()
        sync_summary = self.sync_legacy_trade_calendar(
            required_end=required_end,
            current_date=current_date,
        )
        validation = self.validate_legacy_projection()
        if validation["difference_count"]:
            raise CalendarCoverageError(
                "legacy trade_calendar does not match SH projection"
            )

        return {
            "required_end": required_end,
            "exchange_summary": exchange_summary,
            "legacy_summary": sync_summary,
            "legacy_validation": validation,
        }

    def validate_exchange(self, exchange: str) -> str:
        normalized_exchange = str(exchange or "").strip().upper()
        if normalized_exchange not in set(Exchange.VALID):
            raise ValueError(
                f"invalid exchange: {exchange}. expected one of: "
                f"{', '.join(Exchange.VALID)}"
            )
        return normalized_exchange

    def _build_summary(self, rows: list[dict]) -> dict:
        if not rows:
            raise ValueError("exchange calendar rows must not be empty")

        exchange_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            exchange_rows[row["exchange"]].append(row)

        summary = {
            "exchange_calendars_version": self.provider.library_version(),
            "coverage_start": min(row["calendar_date"] for row in rows),
            "coverage_end": max(row["calendar_date"] for row in rows),
            "exchanges": {},
        }
        for exchange in Exchange.VALID:
            rows_for_exchange = sorted(
                exchange_rows.get(exchange, []),
                key=lambda row: row["calendar_date"],
            )
            if not rows_for_exchange:
                continue
            total_days = len(rows_for_exchange)
            open_days = sum(row["is_open"] for row in rows_for_exchange)
            summary["exchanges"][exchange] = {
                "coverage_start": rows_for_exchange[0]["calendar_date"],
                "coverage_end": rows_for_exchange[-1]["calendar_date"],
                "total_days": total_days,
                "open_days": open_days,
                "closed_days": total_days - open_days,
            }
        return summary

    def _validate_exchange_calendar(self, required_end: str) -> dict:
        validation = self.dao.validate_exchange_calendar_integrity(
            EXCHANGE_START_DATES,
            required_end=required_end,
        )
        sh_open_dates = self.dao.get_open_dates(LEGACY_CALENDAR_EXCHANGE)
        if not sh_open_dates:
            validation["valid"] = False
            validation["issues"].append("SH open-date projection is empty")
        return validation

    def _minimum_required_end(
        self,
        current_date: str,
        required_end: str | None = None,
    ) -> str:
        threshold_end = (
            self._parse_date(current_date)
            + timedelta(days=self.coverage_threshold_days)
        ).strftime("%Y-%m-%d")
        if required_end and required_end > threshold_end:
            return required_end
        return threshold_end

    @staticmethod
    def _minimum_exchange_coverage_end(validation: dict) -> str | None:
        coverage_ends = [
            row["coverage_end"]
            for row in validation.get("coverage", [])
            if row.get("coverage_end")
        ]
        return min(coverage_ends) if coverage_ends else None

    def _is_coverage_insufficient(
        self,
        coverage_end: str | None,
        current_date: str,
    ) -> bool:
        return (
            coverage_end is None
            or self._days_until(coverage_end, current_date)
            < self.coverage_threshold_days
        )

    @staticmethod
    def _days_until(end_date: str | None, current_date: str) -> int | None:
        if not end_date:
            return None
        return (
            CalendarService._parse_date(end_date)
            - CalendarService._parse_date(current_date)
        ).days

    @staticmethod
    def _parse_date(date_value: str):
        return datetime.strptime(date_value, "%Y-%m-%d").date()


calendar_service = CalendarService()
