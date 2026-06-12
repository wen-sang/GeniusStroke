from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from config.constants import DataSource
from config.settings import MARKET_GAP_FILL_MAX_RETRIES
from dao.base_dao import BaseDAO
from utils.validators import ValidationError


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
                        SELECT task.last_error_code
                        FROM dat_market_gap_fill_task task
                        WHERE task.latest_issue_id =
                            dat_data_quality_issue.id
                    ) IN (
                        'NO_SOURCE_DATA',
                        'SKIPPED_UNSUPPORTED_LOF',
                        'SKIPPED_NOT_IN_CATALOG',
                        'SKIPPED_INACTIVE_CATALOG'
                    )
                    THEN 'CONFIRMED'
                    ELSE 'OPEN'
                END
                WHERE id IN ({placeholders})
                  AND EXISTS (
                    SELECT 1
                    FROM dat_market_gap_fill_task task
                    WHERE task.latest_issue_id =
                        dat_data_quality_issue.id
                      AND task.status = 'SKIPPED'
                  )
                """,
                issue_ids,
            )
            return changed

    def claim_due_tasks(
        self,
        run_id: str,
        limit: int,
        running_ttl_minutes: int,
        now_text: str,
        options: Any | None = None,
    ) -> list[dict]:
        groups = self.claim_due_task_groups(
            run_id=run_id,
            batch_size=limit,
            max_tasks=limit,
            running_ttl_minutes=running_ttl_minutes,
            now_text=now_text,
            options=options,
        )
        return [task for group in groups for task in group["tasks"]]

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
            detail_json = ?,
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
            detail_json = ?,
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

    def list_missing_bar_issues_for_batch(self, scan_batch_id: str) -> list[dict]:
        sql = """
        SELECT
            i.id,
            i.asset_code,
            i.trade_date,
            m.exchange,
            m.asset_type,
            NULL AS route_source_id,
            NULL AS route_source_code
        FROM dat_data_quality_issue i
        JOIN sys_asset_meta m ON m.asset_code = i.asset_code
        WHERE i.scan_batch_id = ?
          AND i.rule_code = 'MISSING_TRADING_DAY_BAR'
        ORDER BY i.asset_code, i.trade_date
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (scan_batch_id,))
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

    def get_tickflow_catalog_version(self) -> str:
        sql = """
        SELECT COALESCE(MAX(last_synced_at), '')
        FROM dat_external_asset_catalog
        WHERE source_id = 'tickflow'
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            row = conn.execute(sql).fetchone()
        return str(row[0] or "") if row else ""

    def commit_filled_group(
        self,
        tasks: list[dict],
        rows_by_date: dict[str, dict],
        run_id: str,
        detail_by_date: dict[str, dict],
    ) -> list[dict]:
        if not tasks:
            return []
        ordered_tasks = sorted(tasks, key=lambda item: item["missing_date"])
        asset_code = ordered_tasks[0]["asset_code"]
        from_date = ordered_tasks[0]["missing_date"]
        completed = []
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            for task in ordered_tasks:
                trade_date = task["missing_date"]
                row = rows_by_date.get(trade_date)
                if row is not None:
                    _validate_market_row(row)
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO dat_market_daily (
                            asset_code,
                            trade_date,
                            open,
                            high,
                            low,
                            close,
                            volume,
                            amount,
                            source_id,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["asset_code"],
                            row["trade_date"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                            row["volume"],
                            row["amount"],
                            DataSource.validate_market_daily_source(
                                row["source_id"]
                            ),
                            row["updated_at"],
                        ),
                    )
                cursor.execute(
                    """
                    SELECT source_id
                    FROM dat_market_daily
                    WHERE asset_code = ?
                      AND trade_date = ?
                    """,
                    (asset_code, trade_date),
                )
                source_row = cursor.fetchone()
                if source_row is None:
                    raise ValidationError(
                        f"Market row missing after fill: {asset_code} {trade_date}"
                    )
                completed.append(
                    {
                        "task_id": task["task_id"],
                        "trade_date": trade_date,
                        "source_id": source_row[0],
                    }
                )

            cursor.execute(
                """
                INSERT INTO dat_market_gap_fill_repair_task (
                    asset_code,
                    from_date,
                    status,
                    generation
                )
                VALUES (?, ?, 'PENDING', 1)
                ON CONFLICT(asset_code) DO UPDATE SET
                    from_date = MIN(
                        dat_market_gap_fill_repair_task.from_date,
                        excluded.from_date
                    ),
                    status = 'PENDING',
                    generation =
                        dat_market_gap_fill_repair_task.generation + 1,
                    run_id = NULL,
                    claimed_at = NULL,
                    claim_expires_at = NULL,
                    completed_at = NULL,
                    updated_at = datetime('now', 'localtime')
                """,
                (asset_code, from_date),
            )

            for task, final in zip(ordered_tasks, completed):
                cursor.execute(
                    """
                    UPDATE dat_market_gap_fill_task
                    SET
                        status = 'FILLED',
                        filled_source_id = ?,
                        filled_at = datetime('now', 'localtime'),
                        next_retry_at = NULL,
                        run_id = NULL,
                        claimed_at = NULL,
                        claim_expires_at = NULL,
                        last_error_code = NULL,
                        last_error_message = NULL,
                        detail_json = ?,
                        updated_at = datetime('now', 'localtime')
                    WHERE task_id = ?
                      AND run_id = ?
                      AND status = 'RUNNING'
                    """,
                    (
                        final["source_id"],
                        _json(detail_by_date.get(final["trade_date"])),
                        task["task_id"],
                        run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValidationError(
                        f"LEASE_LOST task_id={task['task_id']}"
                    )
                issue_id = task.get("latest_issue_id")
                if issue_id:
                    cursor.execute(
                        """
                        UPDATE dat_data_quality_issue
                        SET issue_status = 'FIXED'
                        WHERE id = ?
                        """,
                        (issue_id,),
                    )
        return completed

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


def _due_condition_sql() -> str:
    return """
    (
        (
            status = 'PENDING'
            AND (next_retry_at IS NULL OR next_retry_at <= ?)
        )
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
    """


def select_complete_asset_groups(
    groups: list[dict],
    batch_size: int,
    max_tasks: int,
) -> list[dict]:
    selected = []
    selected_count = 0
    soft_limit = min(batch_size, max_tasks)
    for group in groups:
        task_count = int(group.get("task_count") or 0)
        if task_count <= 0:
            continue
        if selected and selected_count + task_count > soft_limit:
            break
        selected.append(group)
        selected_count += task_count
        if selected_count >= soft_limit:
            break
    return selected


def _validate_market_row(row: dict) -> None:
    required = (
        "asset_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source_id",
        "updated_at",
    )
    if any(row.get(column) is None for column in required):
        raise ValidationError("Incomplete market row")
    open_price = float(row["open"])
    high_price = float(row["high"])
    low_price = float(row["low"])
    close_price = float(row["close"])
    if min(open_price, high_price, low_price, close_price) <= 0:
        raise ValidationError("Market OHLC prices must be positive")
    if high_price < max(open_price, low_price, close_price):
        raise ValidationError("Market high price is invalid")
    if low_price > min(open_price, close_price):
        raise ValidationError("Market low price is invalid")
    if float(row["volume"]) < 0 or float(row["amount"]) < 0:
        raise ValidationError("Market volume/amount must be non-negative")


market_gap_fill_dao = MarketGapFillDAO()
