"""add_stock_corporate_action_fields

Revision ID: b2c3d4e5f6a7
Revises: a9c4e5f6b7d8
Create Date: 2026-06-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a9c4e5f6b7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    existing_columns = {
        row[1]
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(account_corporate_action)"
        )
    }
    columns = [
        ("ex_date", "TEXT"),
        ("share_change_subtype", "TEXT"),
        ("tax_mode", "TEXT"),
        ("bundle_ref_id", "TEXT"),
        ("cash_base_qty", "REAL"),
    ]
    for column_name, column_type in columns:
        if column_name not in existing_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE account_corporate_action ADD COLUMN {column_name} {column_type}"
            )

    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_corp_action_bundle_ref "
        "ON account_corporate_action(bundle_ref_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_corp_action_account_bundle "
        "ON account_corporate_action(account_id, bundle_ref_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_corp_action_asset_record_ex "
        "ON account_corporate_action(account_id, asset_code, record_date, ex_date)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_cash_flow_dividend_tax_source "
        "ON account_cash_flow(source_type, source_ref_id, flow_type)"
    )


def downgrade() -> None:
    connection = op.get_bind()
    index_names = [
        "idx_cash_flow_dividend_tax_source",
        "idx_corp_action_asset_record_ex",
        "idx_corp_action_account_bundle",
        "idx_corp_action_bundle_ref",
    ]
    for index_name in index_names:
        connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index_name}")

    existing_columns = {
        row[1]
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(account_corporate_action)"
        )
    }
    for column_name in [
        "cash_base_qty",
        "bundle_ref_id",
        "tax_mode",
        "share_change_subtype",
        "ex_date",
    ]:
        if column_name in existing_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE account_corporate_action DROP COLUMN {column_name}"
            )
