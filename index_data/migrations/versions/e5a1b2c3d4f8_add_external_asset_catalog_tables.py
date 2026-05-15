"""add_external_asset_catalog_tables

Revision ID: e5a1b2c3d4f8
Revises: b1c2d3e4f5a6
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e5a1b2c3d4f8"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS dat_external_asset_catalog (
            catalog_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            external_symbol TEXT NOT NULL,
            asset_code TEXT NOT NULL,
            asset_name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            exchange TEXT,
            market_category TEXT NOT NULL DEFAULT 'EXCHANGE',
            listing_date TEXT,
            source_universe_id TEXT,
            source_universe_name TEXT,
            source_asset_type TEXT,
            source_status TEXT,
            raw_payload TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            last_synced_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            CONSTRAINT uq_external_catalog_source_symbol UNIQUE (source_id, external_symbol)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_external_catalog_source_type_exchange
        ON dat_external_asset_catalog(source_id, asset_type, exchange, is_active)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_external_catalog_code_exchange
        ON dat_external_asset_catalog(asset_code, exchange)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_external_catalog_name
        ON dat_external_asset_catalog(asset_name)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_external_catalog_sync
        ON dat_external_asset_catalog(source_id, is_active, last_synced_at)
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS dat_external_asset_catalog_sync_log (
            sync_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            total_fetched INTEGER NOT NULL DEFAULT 0,
            total_upserted INTEGER NOT NULL DEFAULT 0,
            total_deactivated INTEGER NOT NULL DEFAULT 0,
            deactivation_skipped INTEGER NOT NULL DEFAULT 0,
            skip_reason TEXT,
            error_message TEXT
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_external_catalog_sync_log_source_started
        ON dat_external_asset_catalog_sync_log(source_id, started_at)
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP TABLE IF EXISTS dat_external_asset_catalog_sync_log")
    connection.exec_driver_sql("DROP TABLE IF EXISTS dat_external_asset_catalog")
