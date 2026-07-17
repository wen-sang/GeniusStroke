from __future__ import annotations

import hashlib
import json
from typing import Any

from config.constants import DataSource
from dao.base_dao import BaseDAO
from dao.market_gap_fill.support import _validate_market_row
from utils.validators import ValidationError


class MarketGapFillAuditDAO(BaseDAO):
    @property
    def table_name(self) -> str:
        return "dat_market_gap_fill_audit_apply"

    def list_tasks(self) -> list[dict]:
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM dat_market_gap_fill_task
                ORDER BY task_id
                """
            )
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def snapshot_tasks_and_fingerprint(self) -> tuple[list[dict], str]:
        with self.db_engine.get_connection(readonly=True) as conn:
            conn.execute("BEGIN")
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM dat_market_gap_fill_task
                ORDER BY task_id
                """
            )
            tasks = self._rows_to_dicts(cursor, cursor.fetchall())
            return tasks, _scope_fingerprint_with_connection(conn)

    def compute_scope_fingerprint(self) -> str:
        with self.db_engine.get_connection(readonly=True) as conn:
            return _scope_fingerprint_with_connection(conn)

    def compute_tickflow_catalog_hash(self) -> str:
        with self.db_engine.get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT
                    catalog.external_symbol,
                    catalog.asset_code,
                    catalog.asset_type,
                    catalog.exchange,
                    catalog.market_category,
                    catalog.is_active
                FROM dat_external_asset_catalog catalog
                WHERE catalog.source_id = 'tickflow'
                  AND catalog.asset_code IN (
                      SELECT DISTINCT asset_code
                      FROM dat_market_gap_fill_task
                  )
                ORDER BY
                    catalog.asset_code,
                    catalog.external_symbol,
                    catalog.asset_type,
                    catalog.exchange,
                    catalog.is_active
                """
            ).fetchall()
        return _hash_rows(rows)

    def is_applied(self, audit_id: str, report_hash: str) -> bool:
        with self.db_engine.get_connection(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM dat_market_gap_fill_audit_apply
                WHERE audit_id = ?
                  AND report_hash = ?
                LIMIT 1
                """,
                (audit_id, report_hash),
            ).fetchone()
        return row is not None

    def apply_report(self, report: dict) -> dict:
        audit_id = report["audit_id"]
        report_hash = report["report_hash"]
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT 1
                FROM dat_market_gap_fill_audit_apply
                WHERE audit_id = ?
                  AND report_hash = ?
                LIMIT 1
                """,
                (audit_id, report_hash),
            )
            if cursor.fetchone() is not None:
                return {"status": "already_applied", "audit_id": audit_id}

            current_fingerprint = _scope_fingerprint_with_connection(conn)
            if current_fingerprint != report["scope_fingerprint"]:
                raise ValidationError("LEGACY_AUDIT_SCOPE_CHANGED")

            summary = {
                "filled": 0,
                "confirmed": 0,
                "pending": 0,
                "failed": 0,
            }
            affected_scan_batches = set()
            tickflow_catalog_version = _latest_tickflow_catalog_version(
                cursor
            )
            for item in report["tasks"]:
                self._apply_item(
                    cursor,
                    item,
                    summary,
                    affected_scan_batches,
                    report.get("tdx_package_id"),
                    tickflow_catalog_version,
                )
            self._refresh_scan_batches(cursor, affected_scan_batches)
            cursor.execute(
                """
                INSERT INTO dat_market_gap_fill_audit_apply (
                    audit_id,
                    report_schema_version,
                    report_hash,
                    scope_fingerprint,
                    summary_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    report["report_schema_version"],
                    report_hash,
                    report["scope_fingerprint"],
                    json.dumps(
                        summary,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            return {
                "status": "applied",
                "audit_id": audit_id,
                "summary": summary,
            }

    def _apply_item(
        self,
        cursor,
        item: dict,
        summary: dict,
        affected_scan_batches: set,
        tdx_package_id: str | None,
        tickflow_catalog_version: str | None,
    ) -> None:
        result = item["result"]
        task_id = item["task_id"]
        asset_code = item["asset_code"]
        trade_date = item["missing_date"]
        source_results = item.get("source_results") or {}
        item_tdx_package_id = (
            tdx_package_id if "tdx" in source_results else None
        )
        item_tickflow_catalog_version = (
            tickflow_catalog_version
            if "tickflow" in source_results
            else None
        )
        current_status = self._current_task_status(cursor, task_id)
        if result == "KEEP_FILLED":
            cursor.execute(
                """
                SELECT source_id
                FROM dat_market_daily
                WHERE asset_code = ?
                  AND trade_date = ?
                """,
                (asset_code, trade_date),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValidationError(
                    f"Audit KEEP_FILLED row missing: {task_id}"
                )
            self._mark_filled(
                cursor,
                task_id,
                row[0],
                item_tdx_package_id,
                item_tickflow_catalog_version,
            )
            self._update_issues(
                cursor,
                asset_code,
                trade_date,
                "FIXED",
                affected_scan_batches,
            )
            summary["filled"] += 1
            return
        if result in {"FILL_FROM_TDX", "FILL_FROM_TICKFLOW"}:
            market_row = item.get("market_row")
            _validate_market_row(market_row)
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
                    market_row["asset_code"],
                    market_row["trade_date"],
                    market_row["open"],
                    market_row["high"],
                    market_row["low"],
                    market_row["close"],
                    market_row["volume"],
                    market_row["amount"],
                    DataSource.validate_market_daily_source(
                        market_row["source_id"]
                    ),
                    market_row["updated_at"],
                ),
            )
            self._mark_filled(
                cursor,
                task_id,
                market_row["source_id"],
                item_tdx_package_id,
                item_tickflow_catalog_version,
            )
            self._update_issues(
                cursor,
                asset_code,
                trade_date,
                "FIXED",
                affected_scan_batches,
            )
            self._upsert_repair(cursor, asset_code, trade_date)
            summary["filled"] += 1
            return
        if result.startswith("CONFIRMED_"):
            cursor.execute(
                """
                UPDATE dat_market_gap_fill_task
                SET
                    status = 'CONFIRMED',
                    attempt_count = 0,
                    next_retry_at = NULL,
                    run_id = NULL,
                    claimed_at = NULL,
                    claim_expires_at = NULL,
                    last_error_code = ?,
                    last_error_message = NULL,
                    last_tdx_package_id = COALESCE(
                        ?, last_tdx_package_id
                    ),
                    last_tickflow_catalog_version = COALESCE(
                        ?, last_tickflow_catalog_version
                    ),
                    detail_json = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE task_id = ?
                """,
                (
                    result,
                    item_tdx_package_id,
                    item_tickflow_catalog_version,
                    json.dumps(
                        {"source_results": source_results},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    task_id,
                ),
            )
            self._update_issues(
                cursor,
                asset_code,
                trade_date,
                "CONFIRMED",
                affected_scan_batches,
            )
            summary["confirmed"] += 1
            return
        if result in {
            "PENDING_SOURCE_CATALOG",
            "PENDING_TICKFLOW_DISCOVERY",
        }:
            if current_status in {"CONFIRMED", "FILLED"}:
                summary["confirmed"] += int(current_status == "CONFIRMED")
                summary["filled"] += int(current_status == "FILLED")
                return
            cursor.execute(
                """
                UPDATE dat_market_gap_fill_task
                SET
                    status = 'PENDING',
                    attempt_count = 0,
                    next_retry_at = NULL,
                    run_id = NULL,
                    claimed_at = NULL,
                    claim_expires_at = NULL,
                    last_error_code = ?,
                    last_error_message = NULL,
                    last_tdx_package_id = COALESCE(
                        ?, last_tdx_package_id
                    ),
                    last_tickflow_catalog_version = COALESCE(
                        ?, last_tickflow_catalog_version
                    ),
                    detail_json = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE task_id = ?
                """,
                (
                    result,
                    item_tdx_package_id,
                    item_tickflow_catalog_version,
                    json.dumps(
                        {"source_results": source_results},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    task_id,
                ),
            )
            self._update_issues(
                cursor,
                asset_code,
                trade_date,
                "OPEN",
                affected_scan_batches,
            )
            summary["pending"] += 1
            return
        if result == "FAILED_SOURCE_VALIDATION":
            if current_status in {"CONFIRMED", "FILLED"}:
                summary["confirmed"] += int(current_status == "CONFIRMED")
                summary["filled"] += int(current_status == "FILLED")
                return
            cursor.execute(
                """
                UPDATE dat_market_gap_fill_task
                SET
                    status = 'FAILED',
                    attempt_count = 1,
                    next_retry_at = NULL,
                    run_id = NULL,
                    claimed_at = NULL,
                    claim_expires_at = NULL,
                    last_error_code = ?,
                    last_error_message = NULL,
                    last_tdx_package_id = COALESCE(
                        ?, last_tdx_package_id
                    ),
                    last_tickflow_catalog_version = COALESCE(
                        ?, last_tickflow_catalog_version
                    ),
                    detail_json = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE task_id = ?
                """,
                (
                    result,
                    item_tdx_package_id,
                    item_tickflow_catalog_version,
                    json.dumps(
                        {"source_results": source_results},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    task_id,
                ),
            )
            self._update_issues(
                cursor,
                asset_code,
                trade_date,
                "OPEN",
                affected_scan_batches,
            )
            summary["failed"] += 1
            return
        raise ValidationError(f"Unsupported audit result: {result}")

    @staticmethod
    def _current_task_status(cursor, task_id: int) -> str | None:
        row = cursor.execute(
            """
            SELECT status
            FROM dat_market_gap_fill_task
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _mark_filled(
        cursor,
        task_id: int,
        source_id: str,
        last_tdx_package_id: str | None,
        last_tickflow_catalog_version: str | None,
    ) -> None:
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
                last_tdx_package_id = COALESCE(?, last_tdx_package_id),
                last_tickflow_catalog_version = COALESCE(
                    ?, last_tickflow_catalog_version
                ),
                updated_at = datetime('now', 'localtime')
            WHERE task_id = ?
            """,
            (
                source_id,
                last_tdx_package_id,
                last_tickflow_catalog_version,
                task_id,
            ),
        )

    @staticmethod
    def _update_issues(
        cursor,
        asset_code: str,
        trade_date: str,
        issue_status: str,
        affected_scan_batches: set,
    ) -> None:
        rows = cursor.execute(
            """
            SELECT DISTINCT scan_batch_id
            FROM dat_data_quality_issue
            WHERE asset_code = ?
              AND trade_date = ?
              AND rule_code = 'MISSING_TRADING_DAY_BAR'
            """,
            (asset_code, trade_date),
        ).fetchall()
        affected_scan_batches.update(row[0] for row in rows)
        cursor.execute(
            """
            UPDATE dat_data_quality_issue
            SET issue_status = ?
            WHERE asset_code = ?
              AND trade_date = ?
              AND rule_code = 'MISSING_TRADING_DAY_BAR'
            """,
            (issue_status, asset_code, trade_date),
        )

    @staticmethod
    def _refresh_scan_batches(cursor, scan_batch_ids: set) -> None:
        for scan_batch_id in scan_batch_ids:
            cursor.execute(
                """
                UPDATE dat_data_quality_scan_batch
                SET
                    open_issue_count = (
                        SELECT COUNT(*)
                        FROM dat_data_quality_issue issue
                        WHERE issue.scan_batch_id =
                            dat_data_quality_scan_batch.scan_batch_id
                          AND issue.issue_status = 'OPEN'
                    ),
                    confirmed_issue_count = (
                        SELECT COUNT(*)
                        FROM dat_data_quality_issue issue
                        WHERE issue.scan_batch_id =
                            dat_data_quality_scan_batch.scan_batch_id
                          AND issue.issue_status = 'CONFIRMED'
                    )
                WHERE scan_batch_id = ?
                """,
                (scan_batch_id,),
            )

    @staticmethod
    def _upsert_repair(cursor, asset_code: str, trade_date: str) -> None:
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
            (asset_code, trade_date),
        )


def _latest_tickflow_catalog_version(cursor) -> str | None:
    row = cursor.execute(
        """
        SELECT MAX(finished_at)
        FROM dat_external_asset_catalog_sync_log
        WHERE source_id = 'tickflow'
          AND status = 'success'
          AND deactivation_skipped = 0
        """
    ).fetchone()
    if row is None:
        return None
    return row[0]


def _scope_fingerprint_with_connection(conn) -> str:
    tasks = conn.execute(
        """
        SELECT
            task_id,
            asset_code,
            missing_date,
            exchange,
            asset_type,
            status,
            attempt_count,
            max_attempts,
            last_error_code,
            detail_json,
            updated_at
        FROM dat_market_gap_fill_task
        ORDER BY task_id
        """
    ).fetchall()
    asset_codes = sorted({row[1] for row in tasks})
    if not asset_codes:
        return _hash_rows(tasks)
    placeholders = ",".join("?" for _ in asset_codes)
    assets = conn.execute(
        f"""
        SELECT
            asset_code,
            asset_type,
            exchange,
            listing_date,
            is_active,
            market_category
        FROM sys_asset_meta
        WHERE asset_code IN ({placeholders})
        ORDER BY asset_code
        """,
        asset_codes,
    ).fetchall()
    routes = conn.execute(
        f"""
        SELECT
            asset_code,
            asset_type,
            interface,
            source_id,
            source_code,
            priority
        FROM sys_data_router
        WHERE asset_code IN ({placeholders})
        ORDER BY asset_code, interface, priority, id
        """,
        asset_codes,
    ).fetchall()
    dates = conn.execute(
        f"""
        SELECT asset_code, trade_date
        FROM dat_market_daily
        WHERE asset_code IN ({placeholders})
        ORDER BY asset_code, trade_date
        """,
        asset_codes,
    ).fetchall()
    return _hash_rows(
        [
            ["tasks", *tasks],
            ["assets", *assets],
            ["routes", *routes],
            ["market_dates", *dates],
        ]
    )


def _hash_rows(rows: Any) -> str:
    payload = json.dumps(
        _normalize(rows),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items())
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


market_gap_fill_audit_dao = MarketGapFillAuditDAO()
