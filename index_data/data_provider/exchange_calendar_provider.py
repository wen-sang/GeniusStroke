from __future__ import annotations

from datetime import datetime

import exchange_calendars as xcals
import pandas as pd

from config.constants import Exchange
from utils.logger import logger


EXCHANGE_START_DATES = {
    Exchange.SH: "1990-12-03",
    Exchange.SZ: "1990-12-03",
    Exchange.HK: "1986-01-02",
}


class ExchangeCalendarProvider:
    """Generate natural-day exchange calendars from exchange-calendars."""

    def library_version(self) -> str:
        return getattr(xcals, "__version__", "unknown")

    def default_end(self) -> str:
        xshg_end = self._calendar_default_end("XSHG")
        xhkg_end = self._calendar_default_end("XHKG")
        return min(xshg_end, xhkg_end).strftime("%Y-%m-%d")

    def build_exchange_calendars(self) -> list[dict]:
        end_date = self.default_end()
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sh_rows = self._build_rows(
            exchange=Exchange.SH,
            calendar_code="XSHG",
            start_date=EXCHANGE_START_DATES[Exchange.SH],
            end_date=end_date,
            updated_at=updated_at,
        )
        sz_rows = [
            {**row, "exchange": Exchange.SZ}
            for row in sh_rows
        ]
        hk_rows = self._build_rows(
            exchange=Exchange.HK,
            calendar_code="XHKG",
            start_date=EXCHANGE_START_DATES[Exchange.HK],
            end_date=end_date,
            updated_at=updated_at,
        )

        rows = sh_rows + sz_rows + hk_rows
        self._log_summary(rows)
        return rows

    def _calendar_default_end(self, calendar_code: str) -> pd.Timestamp:
        calendar = xcals.get_calendar(calendar_code)
        return calendar.default_end()

    def _build_rows(
        self,
        exchange: str,
        calendar_code: str,
        start_date: str,
        end_date: str,
        updated_at: str,
    ) -> list[dict]:
        calendar = xcals.get_calendar(
            calendar_code,
            start=start_date,
            end=end_date,
        )
        open_dates = set(calendar.sessions.strftime("%Y-%m-%d"))
        natural_dates = pd.date_range(start=start_date, end=end_date, freq="D")

        return [
            {
                "exchange": exchange,
                "calendar_date": date.strftime("%Y-%m-%d"),
                "is_open": 1 if date.strftime("%Y-%m-%d") in open_dates else 0,
                "updated_at": updated_at,
            }
            for date in natural_dates
        ]

    def _log_summary(self, rows: list[dict]) -> None:
        logger.info(
            "[TRADE_CALENDAR] exchange-calendars version=%s",
            self.library_version(),
        )
        for exchange in Exchange.VALID:
            exchange_rows = [row for row in rows if row["exchange"] == exchange]
            if not exchange_rows:
                continue
            total_days = len(exchange_rows)
            open_days = sum(row["is_open"] for row in exchange_rows)
            closed_days = total_days - open_days
            logger.info(
                "[TRADE_CALENDAR] exchange=%s start=%s end=%s "
                "total_days=%s open_days=%s closed_days=%s",
                exchange,
                exchange_rows[0]["calendar_date"],
                exchange_rows[-1]["calendar_date"],
                total_days,
                open_days,
                closed_days,
            )
