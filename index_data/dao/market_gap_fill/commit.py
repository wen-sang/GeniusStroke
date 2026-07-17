# 文件: dao/market_gap_fill/commit.py
"""缺口治理落库提交：发现行提交、回补组提交、存量对账（方法级单连接事务）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from config.constants import DataSource
from config.settings import MARKET_GAP_FILL_MAX_RETRIES
from utils.validators import ValidationError
from dao.market_gap_fill.support import (
    _json,
    _merge_detail_json,
    _validate_market_row,
)


class CommitMixin:
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
                    SELECT detail_json
                    FROM dat_market_gap_fill_task
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                existing_detail = cursor.fetchone()
                merged_detail = _merge_detail_json(
                    existing_detail[0] if existing_detail else None,
                    detail_by_date.get(final["trade_date"]),
                )
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
                        merged_detail,
                        task["task_id"],
                        run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValidationError(
                        f"LEASE_LOST task_id={task['task_id']}"
                    )
                self._update_gap_issue_status_with_cursor(
                    cursor,
                    asset_code=asset_code,
                    trade_date=final["trade_date"],
                    issue_status="FIXED",
                )
        return completed

    def reconcile_existing_market_rows(
        self,
        asset_code: str | None = None,
    ) -> list[dict]:
        params: tuple[Any, ...] = ()
        asset_filter = ""
        if asset_code:
            asset_filter = "AND task.asset_code = ?"
            params = (asset_code,)
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                f"""
                SELECT
                    task.task_id,
                    task.asset_code,
                    task.missing_date,
                    market.source_id
                FROM dat_market_gap_fill_task task
                JOIN dat_market_daily market
                  ON market.asset_code = task.asset_code
                 AND market.trade_date = task.missing_date
                WHERE task.status != 'FILLED'
                  {asset_filter}
                ORDER BY task.asset_code, task.missing_date
                """,
                params,
            )
            rows = self._rows_to_dicts(cursor, cursor.fetchall())
            for row in rows:
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
                        updated_at = datetime('now', 'localtime')
                    WHERE task_id = ?
                      AND status != 'FILLED'
                    """,
                    (row["source_id"], row["task_id"]),
                )
                self._update_gap_issue_status_with_cursor(
                    cursor,
                    asset_code=row["asset_code"],
                    trade_date=row["missing_date"],
                    issue_status="FIXED",
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
                    (row["asset_code"], row["missing_date"]),
                )
            return rows

    def commit_discovered_rows(
        self,
        scan_batch_id: str,
        detected_at: str,
        asset_code: str,
        exchange: str,
        asset_type: str,
        rows_by_date: dict[str, dict],
        source_id: str,
        evidence_by_date: dict[str, dict],
    ) -> list[str]:
        if not rows_by_date:
            return []
        filled_dates = []
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            for trade_date in sorted(rows_by_date):
                row = rows_by_date[trade_date]
                _validate_market_row(row)
                detail = {
                    "exchange": exchange,
                    "calendar_date": trade_date,
                    "missing_reason": "source_discovered_market_bar",
                    "source_results": {
                        source_id: evidence_by_date.get(trade_date, {})
                    },
                }
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO dat_data_quality_issue (
                        scan_batch_id,
                        asset_code,
                        trade_date,
                        source_table,
                        source_id,
                        entity_type,
                        entity_id,
                        rule_code,
                        severity,
                        issue_group,
                        field_name,
                        actual_value,
                        expected_value,
                        detail_json,
                        issue_status,
                        detected_at
                    )
                    VALUES (
                        ?, ?, ?, 'dat_market_daily', ?, 'ASSET', ?,
                        'MISSING_TRADING_DAY_BAR', 'WARN', 'CONTINUITY',
                        'trade_date', 'missing bar',
                        'market bar discovered by source', ?, 'OPEN', ?
                    )
                    """,
                    (
                        scan_batch_id,
                        asset_code,
                        trade_date,
                        source_id,
                        asset_code,
                        _json(detail),
                        detected_at,
                    ),
                )
                cursor.execute(
                    """
                    SELECT id
                    FROM dat_data_quality_issue
                    WHERE scan_batch_id = ?
                      AND asset_code = ?
                      AND trade_date = ?
                      AND rule_code = 'MISSING_TRADING_DAY_BAR'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (scan_batch_id, asset_code, trade_date),
                )
                issue_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO dat_market_gap_fill_task (
                        asset_code,
                        missing_date,
                        exchange,
                        asset_type,
                        latest_issue_id,
                        max_attempts,
                        detail_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_code, missing_date) DO UPDATE SET
                        exchange = excluded.exchange,
                        asset_type = excluded.asset_type,
                        latest_issue_id = excluded.latest_issue_id,
                        updated_at = datetime('now', 'localtime')
                    WHERE dat_market_gap_fill_task.status != 'FILLED'
                    """,
                    (
                        asset_code,
                        trade_date,
                        exchange,
                        asset_type,
                        issue_id,
                        MARKET_GAP_FILL_MAX_RETRIES,
                        _json(detail),
                    ),
                )
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
                market_source = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT detail_json
                    FROM dat_market_gap_fill_task
                    WHERE asset_code = ?
                      AND missing_date = ?
                    """,
                    (asset_code, trade_date),
                )
                task_detail = cursor.fetchone()
                merged_detail = _merge_detail_json(
                    task_detail[0] if task_detail else None,
                    detail,
                )
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
                    WHERE asset_code = ?
                      AND missing_date = ?
                    """,
                    (
                        market_source,
                        merged_detail,
                        asset_code,
                        trade_date,
                    ),
                )
                self._update_gap_issue_status_with_cursor(
                    cursor,
                    asset_code=asset_code,
                    trade_date=trade_date,
                    issue_status="FIXED",
                )
                filled_dates.append(trade_date)

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
                (asset_code, min(filled_dates)),
            )
        return filled_dates
