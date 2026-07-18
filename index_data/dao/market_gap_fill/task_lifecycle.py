# 文件: dao/market_gap_fill/task_lifecycle.py
"""缺口治理任务生命周期：upsert / claim / mark / defer / reopen。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from config.settings import MARKET_GAP_FILL_MAX_RETRIES
from dao.market_gap_fill.support import (
    _add_minutes,
    _due_condition_sql,
    _json,
    _merge_detail_json,
    _merge_source_result_json,
    _now_text,
    select_complete_asset_groups,
)


class TaskLifecycleMixin:
    def upsert_tasks_from_issues(self, issues: list[dict]) -> int:
        if not issues:
            return 0

        rows = [
            (
                issue["asset_code"],
                issue["trade_date"],
                issue.get("exchange"),
                issue.get("asset_type"),
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
            latest_issue_id,
            max_attempts
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_code, missing_date) DO UPDATE SET
            exchange = excluded.exchange,
            asset_type = excluded.asset_type,
            latest_issue_id = excluded.latest_issue_id,
            updated_at = datetime('now', 'localtime')
        WHERE dat_market_gap_fill_task.status != 'FILLED'
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            changed = cursor.rowcount
            issue_ids = [row[4] for row in rows]
            placeholders = self._build_placeholders(issue_ids)
            cursor.execute(
                f"""
                UPDATE dat_data_quality_issue
                SET issue_status = CASE
                    WHEN (
                        SELECT task.status
                        FROM dat_market_gap_fill_task task
                        WHERE task.latest_issue_id =
                            dat_data_quality_issue.id
                    ) = 'CONFIRMED'
                    THEN 'CONFIRMED'
                    ELSE 'OPEN'
                END
                WHERE id IN ({placeholders})
                  AND EXISTS (
                    SELECT 1
                    FROM dat_market_gap_fill_task task
                    WHERE task.latest_issue_id =
                        dat_data_quality_issue.id
                      AND task.status IN ('CONFIRMED', 'SKIPPED')
                  )
                """,
                issue_ids,
            )
            return changed

    def claim_due_task_groups(
        self,
        run_id: str,
        batch_size: int,
        max_tasks: int,
        running_ttl_minutes: int,
        now_text: str,
        options: Any | None = None,
    ) -> list[dict]:
        claim_expires_at = _add_minutes(now_text, running_ttl_minutes)
        filters_sql, filters_params = self._build_task_filters(options)
        due_sql = _due_condition_sql()
        group_sql = f"""
        SELECT
            COALESCE(exchange, '') AS exchange,
            asset_code,
            MIN(missing_date) AS first_missing_date,
            MIN(task_id) AS first_task_id,
            COUNT(*) AS task_count
        FROM dat_market_gap_fill_task
        WHERE {due_sql}
          AND attempt_count < max_attempts
          {filters_sql}
        GROUP BY COALESCE(exchange, ''), asset_code
        ORDER BY first_missing_date ASC, first_task_id ASC
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                group_sql,
                (now_text, now_text, now_text, *filters_params),
            )
            groups = self._rows_to_dicts(cursor, cursor.fetchall())
            selected = select_complete_asset_groups(
                groups,
                batch_size=batch_size,
                max_tasks=max_tasks,
            )
            if not selected:
                return []

            claimed_groups = []
            for group in selected:
                group_filters = ["asset_code = ?"]
                group_params: list[Any] = [group["asset_code"]]
                if group["exchange"]:
                    group_filters.append("exchange = ?")
                    group_params.append(group["exchange"])
                else:
                    group_filters.append("exchange IS NULL")
                where_group = " AND ".join(group_filters)
                cursor.execute(
                    f"""
                    UPDATE dat_market_gap_fill_task
                    SET
                        status = 'RUNNING',
                        run_id = ?,
                        claimed_at = ?,
                        claim_expires_at = ?,
                        updated_at = datetime('now', 'localtime')
                    WHERE {where_group}
                      AND {_due_condition_sql()}
                      AND attempt_count < max_attempts
                      {filters_sql}
                    """,
                    (
                        run_id,
                        now_text,
                        claim_expires_at,
                        *group_params,
                        now_text,
                        now_text,
                        now_text,
                        *filters_params,
                    ),
                )
                cursor.execute(
                    f"""
                    SELECT *
                    FROM dat_market_gap_fill_task
                    WHERE run_id = ?
                      AND status = 'RUNNING'
                      AND {where_group}
                    ORDER BY missing_date ASC, task_id ASC
                    """,
                    (run_id, *group_params),
                )
                tasks = self._rows_to_dicts(cursor, cursor.fetchall())
                if tasks:
                    claimed_groups.append(
                        {
                            "exchange": group["exchange"],
                            "asset_code": group["asset_code"],
                            "tasks": tasks,
                        }
                    )
            return claimed_groups

    def list_due_tasks(
        self,
        limit: int,
        now_text: str,
        options: Any | None = None,
    ) -> list[dict]:
        filters_sql, filters_params = self._build_task_filters(options)
        sql = f"""
        SELECT *
        FROM dat_market_gap_fill_task
        WHERE {_due_condition_sql()}
          AND attempt_count < max_attempts
          {filters_sql}
        ORDER BY missing_date ASC, task_id ASC
        LIMIT ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                sql,
                (now_text, now_text, now_text, *filters_params, limit),
            )
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def mark_filled(
        self,
        task_id: int,
        run_id: str,
        source_id: str,
        detail: dict[str, Any] | None = None,
    ) -> int:
        sql = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'FILLED',
            filled_source_id = ?,
            filled_at = datetime('now', 'localtime'),
            last_error_code = NULL,
            last_error_message = NULL,
            next_retry_at = NULL,
            run_id = NULL,
            claimed_at = NULL,
            claim_expires_at = NULL,
            detail_json = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
          AND run_id = ?
          AND status = 'RUNNING'
        """
        return self._execute_update(
            sql,
            (source_id, _json(detail), task_id, run_id),
        )

    def mark_confirmed(
        self,
        task_id: int,
        run_id: str,
        confirmation_code: str,
        detail: dict[str, Any] | None = None,
        last_tdx_package_id: str | None = None,
        last_tickflow_catalog_version: str | None = None,
    ) -> int:
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT asset_code, missing_date, detail_json
                FROM dat_market_gap_fill_task
                WHERE task_id = ?
                  AND run_id = ?
                  AND status = 'RUNNING'
                """,
                (task_id, run_id),
            )
            row = cursor.fetchone()
            if row is None:
                return 0
            merged_detail = _merge_detail_json(row[2], detail)
            cursor.execute(
                """
                UPDATE dat_market_gap_fill_task
                SET
                    status = 'CONFIRMED',
                    next_retry_at = NULL,
                    run_id = NULL,
                    claimed_at = NULL,
                    claim_expires_at = NULL,
                    last_error_code = ?,
                    last_error_message = NULL,
                    last_tdx_package_id = COALESCE(?, last_tdx_package_id),
                    last_tickflow_catalog_version = COALESCE(
                        ?, last_tickflow_catalog_version
                    ),
                    detail_json = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE task_id = ?
                  AND run_id = ?
                  AND status = 'RUNNING'
                """,
                (
                    confirmation_code,
                    last_tdx_package_id,
                    last_tickflow_catalog_version,
                    merged_detail,
                    task_id,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                return 0
            self._update_gap_issue_status_with_cursor(
                cursor,
                asset_code=row[0],
                trade_date=row[1],
                issue_status="CONFIRMED",
            )
            return 1

    def mark_skipped(
        self,
        task_id: int,
        run_id: str,
        error_code: str,
        error_message: str,
        detail: dict[str, Any] | None = None,
        increment_attempt: bool = False,
        last_tdx_package_id: str | None = None,
        last_tickflow_catalog_version: str | None = None,
        last_tickflow_config_signature: str | None = None,
        tickflow_retry_after: str | None = None,
    ) -> int:
        attempt_sql = "attempt_count = attempt_count + 1," if increment_attempt else ""
        sql = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'SKIPPED',
            {attempt_sql}
            next_retry_at = NULL,
            run_id = NULL,
            claimed_at = NULL,
            claim_expires_at = NULL,
            last_error_code = ?,
            last_error_message = ?,
            last_tdx_package_id = COALESCE(?, last_tdx_package_id),
            last_tickflow_catalog_version = COALESCE(
                ?, last_tickflow_catalog_version
            ),
            last_tickflow_config_signature = COALESCE(
                ?, last_tickflow_config_signature
            ),
            tickflow_retry_after = ?,
            detail_json = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
          AND run_id = ?
          AND status = 'RUNNING'
        """.format(attempt_sql=attempt_sql)
        return self._execute_update(
            sql,
            (
                error_code,
                error_message[:200],
                last_tdx_package_id,
                last_tickflow_catalog_version,
                last_tickflow_config_signature,
                tickflow_retry_after,
                _json(detail),
                task_id,
                run_id,
            ),
        )

    def mark_failed_retry(
        self,
        task_id: int,
        run_id: str,
        error_code: str,
        error_message: str,
        retry_delay_minutes: int,
        detail: dict[str, Any] | None = None,
    ) -> int:
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
            run_id = NULL,
            claimed_at = NULL,
            claim_expires_at = NULL,
            detail_json = json_patch(
                CASE
                    WHEN json_valid(detail_json) THEN detail_json
                    ELSE '{}'
                END,
                json(?)
            ),
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
          AND run_id = ?
          AND status = 'RUNNING'
        """
        return self._execute_update(
            sql,
            (
                next_retry_at,
                error_code,
                error_message[:200],
                _json(detail),
                task_id,
                run_id,
            ),
        )

    def merge_source_result(
        self,
        task_id: int,
        source_id: str,
        source_result: dict[str, Any],
        run_id: str | None = None,
    ) -> int:
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            filters = ["task_id = ?"]
            params: list[Any] = [task_id]
            if run_id is not None:
                filters.extend(["run_id = ?", "status = 'RUNNING'"])
                params.append(run_id)
            cursor.execute(
                f"""
                SELECT detail_json
                FROM dat_market_gap_fill_task
                WHERE {' AND '.join(filters)}
                """,
                params,
            )
            row = cursor.fetchone()
            if row is None:
                return 0
            merged = _merge_source_result_json(
                row[0],
                source_id,
                source_result,
            )
            cursor.execute(
                f"""
                UPDATE dat_market_gap_fill_task
                SET detail_json = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE {' AND '.join(filters)}
                """,
                (merged, *params),
            )
            return cursor.rowcount

    def defer_task(
        self,
        task_id: int,
        run_id: str,
        retry_delay_minutes: int,
        error_code: str,
        detail: dict[str, Any] | None = None,
    ) -> int:
        now_text = _now_text()
        sql = """
        UPDATE dat_market_gap_fill_task
        SET
            status = 'PENDING',
            next_retry_at = ?,
            last_error_code = ?,
            last_error_message = NULL,
            run_id = NULL,
            claimed_at = NULL,
            claim_expires_at = NULL,
            detail_json = json_patch(
                CASE
                    WHEN json_valid(detail_json) THEN detail_json
                    ELSE '{}'
                END,
                json(?)
            ),
            updated_at = datetime('now', 'localtime')
        WHERE task_id = ?
          AND run_id = ?
          AND status = 'RUNNING'
        """
        return self._execute_update(
            sql,
            (
                _add_minutes(now_text, retry_delay_minutes),
                error_code,
                _json(detail),
                task_id,
                run_id,
            ),
        )

    def renew_group_lease(
        self,
        task_ids: list[int],
        run_id: str,
        running_ttl_minutes: int,
        now_text: str,
    ) -> int:
        if not task_ids:
            return 0
        placeholders = self._build_placeholders(task_ids)
        sql = f"""
        UPDATE dat_market_gap_fill_task
        SET
            claim_expires_at = ?,
            updated_at = datetime('now', 'localtime')
        WHERE task_id IN ({placeholders})
          AND run_id = ?
          AND status = 'RUNNING'
        """
        return self._execute_update(
            sql,
            (
                _add_minutes(now_text, running_ttl_minutes),
                *task_ids,
                run_id,
            ),
        )

    def reopen_tasks_for_sources(
        self,
        tdx_package_id: str,
        catalog_version: str,
        config_signature: str,
        now_text: str,
    ) -> int:
        return self._execute_update(
            """
            UPDATE dat_market_gap_fill_task
            SET
                status = 'PENDING',
                attempt_count = CASE
                    WHEN last_error_code = 'RETRY_EXHAUSTED' THEN 0
                    ELSE attempt_count
                END,
                next_retry_at = NULL,
                run_id = NULL,
                claimed_at = NULL,
                claim_expires_at = NULL,
                updated_at = datetime('now', 'localtime')
            WHERE status = 'SKIPPED'
              AND (
                (
                    last_tdx_package_id IS NOT NULL
                    AND last_tdx_package_id != ?
                )
                OR (
                    last_error_code = 'NO_SOURCE_DATA'
                    AND tickflow_retry_after IS NOT NULL
                    AND tickflow_retry_after <= ?
                )
                OR (
                    last_error_code IN (
                        'SKIPPED_NOT_IN_CATALOG',
                        'SKIPPED_INACTIVE_CATALOG'
                    )
                    AND COALESCE(last_tickflow_catalog_version, '') != ?
                )
                OR (
                    last_error_code = 'RETRY_EXHAUSTED'
                    AND COALESCE(last_tickflow_config_signature, '') != ?
                )
              )
            """,
            (
                tdx_package_id,
                now_text,
                catalog_version,
                config_signature,
            ),
        )

    def force_reopen_asset(
        self,
        asset_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        filters = ["asset_code = ?", "status != 'FILLED'"]
        params: list[Any] = [asset_code]
        if start_date:
            filters.append("missing_date >= ?")
            params.append(start_date)
        if end_date:
            filters.append("missing_date <= ?")
            params.append(end_date)
        return self._execute_update(
            f"""
            UPDATE dat_market_gap_fill_task
            SET
                status = 'PENDING',
                attempt_count = 0,
                next_retry_at = NULL,
                run_id = NULL,
                claimed_at = NULL,
                claim_expires_at = NULL,
                updated_at = datetime('now', 'localtime')
            WHERE {' AND '.join(filters)}
            """,
            tuple(params),
        )

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
