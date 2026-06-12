from __future__ import annotations

from datetime import datetime, timedelta

from config import settings
from dao.base_dao import BaseDAO


class TickFlowGapFillRuntimeDAO(BaseDAO):
    @property
    def table_name(self) -> str:
        return "dat_tickflow_gap_fill_runtime"

    def get_runtime(self) -> dict:
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM dat_tickflow_gap_fill_runtime
                WHERE runtime_id = 1
                """
            )
            return self._row_to_dict(cursor, cursor.fetchone())

    def reserve_request_start(
        self,
        now_text: str,
        interval_seconds: float,
        config_signature: str,
    ) -> dict:
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT *
                FROM dat_tickflow_gap_fill_runtime
                WHERE runtime_id = 1
                """
            )
            runtime = self._row_to_dict(cursor, cursor.fetchone())
            if (
                runtime.get("breaker_state") == "OPEN"
                and runtime.get("breaker_until")
                and runtime["breaker_until"] > now_text
                and runtime.get("breaker_config_signature") == config_signature
            ):
                return {
                    "reserved": False,
                    "breaker_open": True,
                    "breaker_reason": runtime.get("breaker_reason"),
                    "wait_seconds": 0.0,
                }

            last_started = runtime.get("last_request_started_at")
            wait_seconds = _remaining_wait(
                last_started,
                now_text,
                interval_seconds,
            )
            if wait_seconds > 0:
                return {
                    "reserved": False,
                    "breaker_open": False,
                    "wait_seconds": wait_seconds,
                }

            cursor.execute(
                """
                UPDATE dat_tickflow_gap_fill_runtime
                SET
                    last_request_started_at = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE runtime_id = 1
                """,
                (now_text,),
            )
            return {
                "reserved": True,
                "breaker_open": False,
                "wait_seconds": 0.0,
            }

    def record_success(self) -> None:
        self._execute_update(
            """
            UPDATE dat_tickflow_gap_fill_runtime
            SET
                breaker_state = 'CLOSED',
                breaker_reason = NULL,
                breaker_until = NULL,
                breaker_config_signature = NULL,
                consecutive_error_count = 0,
                updated_at = datetime('now', 'localtime')
            WHERE runtime_id = 1
            """
        )

    def record_error(
        self,
        category: str,
        now_text: str,
        config_signature: str,
    ) -> dict:
        immediate = {
            "AUTH_ERROR",
            "PERMISSION_ERROR",
            "QUOTA_EXHAUSTED",
        }
        transient = {
            "RATE_LIMITED",
            "TIMEOUT",
            "CONNECTION_ERROR",
            "SERVER_ERROR",
            "INVALID_RESPONSE",
        }
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT consecutive_error_count
                FROM dat_tickflow_gap_fill_runtime
                WHERE runtime_id = 1
                """
            )
            row = cursor.fetchone()
            previous_count = int(row[0] or 0)
            count = (
                previous_count + 1
                if category in immediate | transient
                else previous_count
            )
            should_open = (
                category in immediate
                or category in transient
                and count
                >= settings.TICKFLOW_GAP_FILL_BREAKER_CONSECUTIVE_ERRORS
            )
            if should_open:
                duration = (
                    timedelta(hours=settings.TICKFLOW_GAP_FILL_AUTH_BREAKER_HOURS)
                    if category in immediate
                    else timedelta(
                        minutes=settings.TICKFLOW_GAP_FILL_TRANSIENT_BREAKER_MINUTES
                    )
                )
                breaker_until = (
                    _parse_datetime(now_text) + duration
                ).isoformat(sep=" ", timespec="microseconds")
                cursor.execute(
                    """
                    UPDATE dat_tickflow_gap_fill_runtime
                    SET
                        breaker_state = 'OPEN',
                        breaker_reason = ?,
                        breaker_until = ?,
                        breaker_config_signature = ?,
                        consecutive_error_count = ?,
                        updated_at = datetime('now', 'localtime')
                    WHERE runtime_id = 1
                    """,
                    (
                        category,
                        breaker_until,
                        config_signature,
                        count,
                    ),
                )
                return {
                    "breaker_open": True,
                    "breaker_reason": category,
                    "breaker_until": breaker_until,
                    "consecutive_error_count": count,
                }
            cursor.execute(
                """
                UPDATE dat_tickflow_gap_fill_runtime
                SET
                    consecutive_error_count = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE runtime_id = 1
                """,
                (count,),
            )
            return {
                "breaker_open": False,
                "breaker_reason": None,
                "breaker_until": None,
                "consecutive_error_count": count,
            }


def _remaining_wait(
    last_started: str | None,
    now_text: str,
    interval_seconds: float,
) -> float:
    if not last_started:
        return 0.0
    last_value = _parse_datetime(last_started)
    now_value = _parse_datetime(now_text)
    ready_at = last_value + timedelta(seconds=interval_seconds)
    return max(0.0, (ready_at - now_value).total_seconds())


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


tickflow_gap_fill_runtime_dao = TickFlowGapFillRuntimeDAO()
