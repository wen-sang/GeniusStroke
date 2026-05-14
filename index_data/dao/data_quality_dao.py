from __future__ import annotations

from core.data_quality.models import DataQualityIssue
from core.data_quality.models import SCAN_SCOPE_FULL
from core.data_quality.models import SOURCE_TABLE_MARKET_DAILY
from core.data_quality.models import TRIGGER_MANUAL
from dao.base_dao import BaseDAO


class DataQualityDAO(BaseDAO):
    @property
    def table_name(self) -> str:
        return "dat_data_quality_issue"

    def create_running_batch(self, scan_batch_id: str, started_at: str) -> None:
        sql = """
        INSERT INTO dat_data_quality_scan_batch (
            scan_batch_id,
            source_table,
            trigger_type,
            scan_scope,
            status,
            started_at,
            scanned_rows,
            issue_count
        )
        VALUES (?, ?, ?, ?, 'RUNNING', ?, 0, 0)
        """
        params = (
            scan_batch_id,
            SOURCE_TABLE_MARKET_DAILY,
            TRIGGER_MANUAL,
            SCAN_SCOPE_FULL,
            started_at,
        )
        self._execute_update(sql, params)

    def fetch_market_daily_rows(self) -> list[dict]:
        sql = """
        SELECT
            md.rowid AS market_row_id,
            md.asset_code,
            md.trade_date,
            md.open,
            md.high,
            md.low,
            md.close,
            md.volume,
            md.amount,
            md.source_id,
            md.updated_at,
            am.asset_code AS meta_asset_code,
            am.asset_name,
            am.asset_type,
            am.exchange,
            am.listing_date
        FROM dat_market_daily md
        LEFT JOIN sys_asset_meta am
            ON md.asset_code = am.asset_code
        ORDER BY md.asset_code, md.trade_date
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def fetch_exchange_calendar_rows(self) -> list[dict]:
        sql = """
        SELECT
            exchange,
            calendar_date,
            is_open,
            updated_at
        FROM trade_calendar_exchange
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def complete_success_batch(
        self,
        scan_batch_id: str,
        issues: list[DataQualityIssue],
        scanned_rows: int,
        report_path: str,
        finished_at: str,
    ) -> int:
        insert_sql = """
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        update_sql = """
        UPDATE dat_data_quality_scan_batch
        SET
            status = 'SUCCESS',
            finished_at = ?,
            scanned_rows = ?,
            issue_count = ?,
            report_path = ?,
            error_message = NULL
        WHERE scan_batch_id = ?
        """
        with self.db_engine.get_connection(readonly=False) as conn:
            cursor = conn.cursor()
            if issues:
                cursor.executemany(
                    insert_sql,
                    [issue.to_db_tuple() for issue in issues],
                )
            inserted_count = self.count_issues_for_batch(
                scan_batch_id,
                conn=conn,
            )
            cursor.execute(
                update_sql,
                (
                    finished_at,
                    scanned_rows,
                    inserted_count,
                    report_path,
                    scan_batch_id,
                ),
            )
        return inserted_count

    def mark_batch_failed(
        self,
        scan_batch_id: str,
        scanned_rows: int,
        error_message: str,
        finished_at: str,
    ) -> None:
        sql = """
        UPDATE dat_data_quality_scan_batch
        SET
            status = 'FAILED',
            finished_at = ?,
            scanned_rows = ?,
            issue_count = 0,
            report_path = NULL,
            error_message = ?
        WHERE scan_batch_id = ?
        """
        self._execute_update(
            sql,
            (finished_at, scanned_rows, error_message[:1000], scan_batch_id),
        )

    def count_issues_for_batch(self, scan_batch_id: str, conn=None) -> int:
        sql = """
        SELECT COUNT(*)
        FROM dat_data_quality_issue
        WHERE scan_batch_id = ?
        """
        if conn is not None:
            return int(conn.execute(sql, (scan_batch_id,)).fetchone()[0])
        with self.db_engine.get_connection(readonly=True) as read_conn:
            return int(read_conn.execute(sql, (scan_batch_id,)).fetchone()[0])

    def get_batch(self, scan_batch_id: str) -> dict:
        sql = """
        SELECT *
        FROM dat_data_quality_scan_batch
        WHERE scan_batch_id = ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (scan_batch_id,))
            return self._row_to_dict(cursor, cursor.fetchone())

    def get_issues_for_batch(self, scan_batch_id: str) -> list[dict]:
        sql = """
        SELECT *
        FROM dat_data_quality_issue
        WHERE scan_batch_id = ?
        ORDER BY id
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (scan_batch_id,))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def get_latest_success_batch(self) -> dict:
        sql = """
        SELECT *
        FROM dat_data_quality_scan_batch
        WHERE status = 'SUCCESS'
        ORDER BY started_at DESC, scan_batch_id DESC
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            return self._row_to_dict(cursor, cursor.fetchone())


data_quality_dao = DataQualityDAO()
