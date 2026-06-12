from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from dao.base_dao import BaseDAO


class MarketGapFillRepairDAO(BaseDAO):
    @property
    def table_name(self) -> str:
        return "dat_market_gap_fill_repair_task"

    def upsert_repair(
        self,
        asset_code: str,
        from_date: str,
        cursor=None,
    ) -> int:
        sql = """
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
            generation = dat_market_gap_fill_repair_task.generation + 1,
            run_id = NULL,
            claimed_at = NULL,
            claim_expires_at = NULL,
            completed_at = NULL,
            updated_at = datetime('now', 'localtime')
        """
        if cursor is not None:
            return cursor.execute(sql, (asset_code, from_date)).rowcount
        return self._execute_update(sql, (asset_code, from_date))

    def claim_due(
        self,
        run_id: str,
        sync_id: str,
        limit: int,
        ttl_minutes: int,
        now_text: str,
        asset_code: str | None = None,
    ) -> list[dict]:
        expires_at = _add_minutes(now_text, ttl_minutes)
        asset_filter = "AND asset_code = ?" if asset_code else ""
        asset_params = (asset_code,) if asset_code else ()
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                f"""
                UPDATE dat_market_gap_fill_repair_task
                SET
                    status = 'RUNNING',
                    run_id = ?,
                    claimed_at = ?,
                    claim_expires_at = ?,
                    last_attempt_sync_id = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE repair_id IN (
                    SELECT repair_id
                    FROM dat_market_gap_fill_repair_task
                    WHERE (
                            status IN ('PENDING', 'FAILED')
                            OR (
                                status = 'RUNNING'
                                AND claim_expires_at <= ?
                            )
                        )
                      AND (
                        last_attempt_sync_id IS NULL
                        OR last_attempt_sync_id != ?
                      )
                      {asset_filter}
                    ORDER BY from_date ASC, repair_id ASC
                    LIMIT ?
                )
                """,
                (
                    run_id,
                    now_text,
                    expires_at,
                    sync_id,
                    now_text,
                    sync_id,
                    *asset_params,
                    limit,
                ),
            )
            cursor.execute(
                """
                SELECT *
                FROM dat_market_gap_fill_repair_task
                WHERE run_id = ?
                  AND status = 'RUNNING'
                ORDER BY from_date ASC, repair_id ASC
                """,
                (run_id,),
            )
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def mark_completed(
        self,
        repair_id: int,
        run_id: str,
        generation: int,
        detail: dict[str, Any],
    ) -> int:
        return self._execute_update(
            """
            UPDATE dat_market_gap_fill_repair_task
            SET
                status = 'COMPLETED',
                run_id = NULL,
                claimed_at = NULL,
                claim_expires_at = NULL,
                last_failed_stage = NULL,
                last_error_code = NULL,
                last_error_message = NULL,
                detail_json = ?,
                completed_at = datetime('now', 'localtime'),
                updated_at = datetime('now', 'localtime')
            WHERE repair_id = ?
              AND run_id = ?
              AND generation = ?
              AND status = 'RUNNING'
            """,
            (_json(detail), repair_id, run_id, generation),
        )

    def mark_failed(
        self,
        repair_id: int,
        run_id: str,
        generation: int,
        stage: str,
        error_code: str,
        error_message: str,
        detail: dict[str, Any],
    ) -> int:
        return self._execute_update(
            """
            UPDATE dat_market_gap_fill_repair_task
            SET
                status = 'FAILED',
                attempt_count = attempt_count + 1,
                run_id = NULL,
                claimed_at = NULL,
                claim_expires_at = NULL,
                last_failed_stage = ?,
                last_error_code = ?,
                last_error_message = ?,
                detail_json = ?,
                updated_at = datetime('now', 'localtime')
            WHERE repair_id = ?
              AND run_id = ?
              AND generation = ?
              AND status = 'RUNNING'
            """,
            (
                stage,
                error_code,
                error_message[:200],
                _json(detail),
                repair_id,
                run_id,
                generation,
            ),
        )


def _json(detail: dict[str, Any]) -> str:
    return json.dumps(detail, ensure_ascii=False, sort_keys=True)


def _add_minutes(now_text: str, minutes: int) -> str:
    value = datetime.strptime(now_text, "%Y-%m-%d %H:%M:%S")
    return (value + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


market_gap_fill_repair_dao = MarketGapFillRepairDAO()
