"""add_data_quality_tables

Revision ID: f6a7b8c9d0e1
Revises: e5a1b2c3d4f6
Create Date: 2026-05-08 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5a1b2c3d4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    raw_connection = connection.connection

    raw_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dat_data_quality_scan_batch (
            scan_batch_id TEXT PRIMARY KEY,
            source_table TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            scan_scope TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            scanned_rows INTEGER NOT NULL DEFAULT 0,
            issue_count INTEGER NOT NULL DEFAULT 0,
            report_path TEXT,
            error_message TEXT,
            CONSTRAINT ck_quality_scan_batch_source_table
                CHECK (source_table IN ('dat_market_daily')),
            CONSTRAINT ck_quality_scan_batch_trigger_type
                CHECK (trigger_type IN ('MANUAL', 'DAILY_JOB')),
            CONSTRAINT ck_quality_scan_batch_scan_scope
                CHECK (scan_scope IN ('FULL', 'INCREMENTAL')),
            CONSTRAINT ck_quality_scan_batch_status
                CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'))
        );

        CREATE TABLE IF NOT EXISTS dat_data_quality_issue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_batch_id TEXT NOT NULL,
            asset_code TEXT,
            trade_date TEXT,
            source_table TEXT NOT NULL,
            source_id TEXT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            rule_code TEXT NOT NULL,
            severity TEXT NOT NULL,
            issue_group TEXT NOT NULL,
            field_name TEXT,
            actual_value TEXT,
            expected_value TEXT,
            detail_json TEXT NOT NULL,
            issue_status TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            CONSTRAINT fk_quality_issue_batch
                FOREIGN KEY (scan_batch_id)
                REFERENCES dat_data_quality_scan_batch(scan_batch_id),
            CONSTRAINT ck_quality_issue_severity
                CHECK (severity IN ('ERROR', 'WARN', 'CANDIDATE')),
            CONSTRAINT ck_quality_issue_group
                CHECK (issue_group IN (
                    'META', 'CALENDAR', 'OHLC',
                    'VOLUME_AMOUNT', 'CONTINUITY'
                )),
            CONSTRAINT ck_quality_issue_status
                CHECK (issue_status IN (
                    'OPEN', 'IGNORED', 'CONFIRMED', 'FIXED'
                )),
            CONSTRAINT ck_quality_issue_entity_type
                CHECK (entity_type IN (
                    'MARKET_ROW', 'ASSET', 'EXCHANGE', 'CALENDAR_DATE'
                ))
        );

        CREATE INDEX IF NOT EXISTS idx_quality_scan_batch_status_started
        ON dat_data_quality_scan_batch(status, started_at);

        CREATE INDEX IF NOT EXISTS idx_quality_issue_batch
        ON dat_data_quality_issue(scan_batch_id);

        CREATE INDEX IF NOT EXISTS idx_quality_issue_asset_date
        ON dat_data_quality_issue(asset_code, trade_date);

        CREATE INDEX IF NOT EXISTS idx_quality_issue_rule
        ON dat_data_quality_issue(rule_code);

        CREATE INDEX IF NOT EXISTS idx_quality_issue_status
        ON dat_data_quality_issue(issue_status);

        CREATE INDEX IF NOT EXISTS idx_quality_issue_source
        ON dat_data_quality_issue(source_id);

        CREATE INDEX IF NOT EXISTS idx_quality_issue_entity
        ON dat_data_quality_issue(entity_type, entity_id);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_quality_issue_batch_key
        ON dat_data_quality_issue(
            scan_batch_id,
            source_table,
            entity_type,
            COALESCE(entity_id, ''),
            COALESCE(asset_code, ''),
            COALESCE(trade_date, ''),
            rule_code,
            COALESCE(field_name, '')
        );
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    index_names = [
        "uq_quality_issue_batch_key",
        "idx_quality_issue_entity",
        "idx_quality_issue_source",
        "idx_quality_issue_status",
        "idx_quality_issue_rule",
        "idx_quality_issue_asset_date",
        "idx_quality_issue_batch",
        "idx_quality_scan_batch_status_started",
    ]
    for index_name in index_names:
        connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index_name}")
    connection.exec_driver_sql("DROP TABLE IF EXISTS dat_data_quality_issue")
    connection.exec_driver_sql(
        "DROP TABLE IF EXISTS dat_data_quality_scan_batch"
    )
