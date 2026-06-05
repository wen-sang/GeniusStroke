from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from config.constants import DataInterface
from config.settings import MARKET_GAP_FILL_MAX_RETRIES
from dao.base_dao import BaseDAO


class MarketGapFillDAO(BaseDAO):
    """历史行情缺口回补任务 DAO。"""

    @property
    def table_name(self) -> str:
        return "dat_market_gap_fill_task"

    def upsert_tasks_from_issues(self, issues: list[dict]) -> int:
        if not issues:
            return 0

        rows = [
            (
                issue["asset_code"],
                issue["trade_date"],
                issue.get("exchange"),
                issue.get("asset_type"),
                issue.get("route_source_id"),
                issue.get("route_source_code"),
                issue["id"],
                MARKET_GAP_FILL_MAX_RETRIES,
            )
            for issue in issues
            if issue.get("asset_code") and issue.get("trade_date")
        ]
        if not rows:
            return 0

        sql = """
        INSERT INTO dat_market_gap_fill_task (
            asset_code,
            missing_date,
            exchange,
            asset_type,
            route_source_id,
            route_source_code,
            latest_issue_id,
            max_attempts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_code, missing_date) DO UPDATE SET
            exchange = excluded.exchange,
            asset_type = excluded.asset_type,
            route_source_id = excluded.route_source_id,
            route_source_code = excluded.route_source_code,
            latest_issue_id = excluded.latest_issue_id,
            updated_at = datetime('now', 'localtime')
        WHERE dat_market_gap_fill_task.status != 'FILLED'
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            return cursor.rowcount

    def claim_due_tasks(
        self,
        run_id: str,
        limit: int,
        running_ttl_minutes: int,
        now_text: str,
        options: Any | None = None,
    ) -> list[dict]:
        claim_expires_at = _add_minutes(now_text, running_ttl_minutes)
        filters_sql, filters_params = self._build_task_filters(options)
        sql_update = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'RUNNING',
            run_id = ?,
            claimed_at = ?,
            claim_expires_at = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id IN (
            SELECT task_id
            FROM dat_market_gap_fill_task
            WHERE (
                    status = 'PENDING'
                    OR (
                        status = 'FAILED'
                        AND attempt_count < max_attempts
                        AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    )
                    OR (
                        status = 'RUNNING'
                        AND claim_expires_at IS NOT NULL
                        AND claim_expires_at <= ?
                    )
                )
              AND attempt_count < max_attempts
              {filters_sql}
            ORDER BY missing_date ASC, task_id ASC
            LIMIT ?
        )
        """.format(filters_sql=filters_sql)
        sql_select = """
        SELECT *
        FROM dat_market_gap_fill_task
        WHERE run_id = ?
          AND status = 'RUNNING'
        ORDER BY missing_date ASC, task_id ASC
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                sql_update,
                (
                    run_id,
                    now_text,
                    claim_expires_at,
                    now_text,
                    now_text,
                    *filters_params,
                    limit,
                ),
            )
            cursor.execute(sql_select, (run_id,))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def list_due_tasks(
        self,
        limit: int,
        now_text: str,
        options: Any | None = None,
    ) -> list[dict]:
        filters_sql, filters_params = self._build_task_filters(options)
        sql = """
        SELECT *
        FROM dat_market_gap_fill_task
        WHERE (
                status = 'PENDING'
                OR (
                    status = 'FAILED'
                    AND attempt_count < max_attempts
                    AND (next_retry_at IS NULL OR next_retry_at <= ?)
                )
                OR (
                    status = 'RUNNING'
                    AND claim_expires_at IS NOT NULL
                    AND claim_expires_at <= ?
                )
            )
          AND attempt_count < max_attempts
          {filters_sql}
        ORDER BY missing_date ASC, task_id ASC
        LIMIT ?
        """.format(filters_sql=filters_sql)
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (now_text, now_text, *filters_params, limit))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def mark_filled(
        self,
        task_id: int,
        source_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        sql = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'FILLED',
            attempt_count = attempt_count + 1,
            filled_source_id = ?,
            filled_at = datetime('now', 'localtime'),
            last_error_code = NULL,
            last_error_message = NULL,
            detail_json = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
        """
        self._execute_update(sql, (source_id, _json(detail), task_id))

    def mark_skipped(
        self,
        task_id: int,
        error_code: str,
        error_message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        sql = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'SKIPPED',
            attempt_count = attempt_count + 1,
            last_error_code = ?,
            last_error_message = ?,
            detail_json = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
        """
        self._execute_update(
            sql,
            (error_code, error_message[:1000], _json(detail), task_id),
        )

    def mark_failed_retry(
        self,
        task_id: int,
        error_code: str,
        error_message: str,
        retry_delay_minutes: int,
        detail: dict[str, Any] | None = None,
    ) -> None:
        now_text = _now_text()
        next_retry_at = _add_minutes(now_text, retry_delay_minutes)
        sql = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'FAILED',
            attempt_count = attempt_count + 1,
            next_retry_at = ?,
            last_error_code = ?,
            last_error_message = ?,
            detail_json = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
        """
        self._execute_update(
            sql,
            (
                next_retry_at,
                error_code,
                error_message[:1000],
                _json(detail),
                task_id,
            ),
        )

    def defer_task(
        self,
        task_id: int,
        retry_delay_minutes: int,
        detail: dict[str, Any] | None = None,
    ) -> None:
        now_text = _now_text()
        sql = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'PENDING',
            next_retry_at = ?,
            detail_json = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
        """
        self._execute_update(
            sql,
            (_add_minutes(now_text, retry_delay_minutes), _json(detail), task_id),
        )

    def list_missing_bar_issues_for_batch(self, scan_batch_id: str) -> list[dict]:
        sql = """
        SELECT
            i.id,
            i.asset_code,
            i.trade_date,
            m.exchange,
            m.asset_type,
            r.source_id AS route_source_id,
            r.source_code AS route_source_code
        FROM dat_data_quality_issue i
        JOIN sys_asset_meta m ON m.asset_code = i.asset_code
        LEFT JOIN sys_data_router r
          ON r.asset_code = i.asset_code
         AND r.interface = ?
        WHERE i.scan_batch_id = ?
          AND i.rule_code = 'MISSING_TRADING_DAY_BAR'
        ORDER BY i.asset_code, i.trade_date
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (DataInterface.DAILY_BAR, scan_batch_id))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def get_asset_state(self, asset_code: str) -> dict:
        sql = """
        SELECT *
        FROM dat_market_gap_fill_asset_state
        WHERE asset_code = ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code,))
            return self._row_to_dict(cursor, cursor.fetchone())

    def upsert_asset_state(
        self,
        asset_code: str,
        target_start_date: str,
        earliest_generated_date: str | None,
    ) -> None:
        sql = """
        INSERT INTO dat_market_gap_fill_asset_state (
            asset_code,
            target_start_date,
            earliest_generated_date,
            updated_at
        )
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(asset_code) DO UPDATE SET
            target_start_date = excluded.target_start_date,
            earliest_generated_date = excluded.earliest_generated_date,
            updated_at = datetime('now', 'localtime')
        """
        self._execute_update(
            sql,
            (asset_code, target_start_date, earliest_generated_date),
        )

    def has_market_row(self, asset_code: str, trade_date: str) -> bool:
        sql = """
        SELECT 1
        FROM dat_market_daily
        WHERE asset_code = ?
          AND trade_date = ?
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            return conn.execute(sql, (asset_code, trade_date)).fetchone() is not None

    def tickflow_catalog_has_asset(self, asset_code: str) -> bool:
        sql = """
        SELECT 1
        FROM dat_external_asset_catalog
        WHERE source_id = 'tickflow'
          AND asset_code = ?
          AND is_active = 1
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            return conn.execute(sql, (asset_code,)).fetchone() is not None

    def get_tickflow_catalog_status(self, asset_code: str) -> str:
        sql = """
        SELECT is_active
        FROM dat_external_asset_catalog
        WHERE source_id = 'tickflow'
          AND asset_code = ?
        ORDER BY is_active DESC
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            row = conn.execute(sql, (asset_code,)).fetchone()
        if row is None:
            return "absent"
        return "active" if int(row[0] or 0) == 1 else "inactive"

    def find_affected_accounts_by_asset_dates(
        self,
        min_filled_date_by_code: dict[str, str],
    ) -> list[dict]:
        if not min_filled_date_by_code:
            return []

        asset_codes = sorted(min_filled_date_by_code)
        placeholders = self._build_placeholders(asset_codes)
        sql = f"""
        WITH affected AS (
            SELECT
                account_id,
                asset_code,
                MIN(substr(trade_time, 1, 10)) AS fact_date
            FROM trade_order
            WHERE status = 1
              AND asset_code IN ({placeholders})
            GROUP BY account_id, asset_code
            UNION ALL
            SELECT
                account_id,
                asset_code,
                MIN(effective_date) AS fact_date
            FROM account_corporate_action
            WHERE status IN ('CONFIRMED', 'APPLIED', 'ACTIVE')
              AND asset_code IN ({placeholders})
            GROUP BY account_id, asset_code
        )
        SELECT account_id, asset_code, MIN(fact_date) AS fact_date
        FROM affected
        GROUP BY account_id, asset_code
        ORDER BY account_id, asset_code
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (*asset_codes, *asset_codes))
            rows = self._rows_to_dicts(cursor, cursor.fetchall())

        result = []
        for row in rows:
            asset_code = row["asset_code"]
            filled_date = min_filled_date_by_code.get(asset_code)
            fact_date = row.get("fact_date")
            if not filled_date or not fact_date:
                continue
            result.append(
                {
                    "account_id": row["account_id"],
                    "asset_code": asset_code,
                    "from_date": max(fact_date, filled_date),
                }
            )
        return result

    @staticmethod
    def _build_task_filters(
        options: Any | None,
    ) -> tuple[str, list[Any]]:
        if options is None:
            return "", []

        filters = []
        params: list[Any] = []
        if options.asset_code:
            filters.append("asset_code = ?")
            params.append(options.asset_code)
        if options.start_date:
            filters.append("missing_date >= ?")
            params.append(options.start_date)
        if options.end_date:
            filters.append("missing_date <= ?")
            params.append(options.end_date)
        if not filters:
            return "", []
        return " AND " + " AND ".join(filters), params


def _json(detail: dict[str, Any] | None) -> str:
    return json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _add_minutes(now_text: str, minutes: int) -> str:
    dt = datetime.strptime(now_text, "%Y-%m-%d %H:%M:%S")
    return (dt + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


market_gap_fill_dao = MarketGapFillDAO()
