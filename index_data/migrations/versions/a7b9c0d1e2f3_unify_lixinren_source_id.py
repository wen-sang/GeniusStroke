"""unify_lixinren_source_id

Revision ID: a7b9c0d1e2f3
Revises: f6a7b8c9d0e1
Create Date: 2026-05-08 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a7b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    raw_connection = connection.connection

    raw_connection.executescript(
        """
        UPDATE sys_data_router
        SET source_id = 'lixinren'
        WHERE source_id = 'lixingren';

        UPDATE dat_market_daily
        SET source_id = 'lixinren'
        WHERE source_id = 'lixingren';

        UPDATE dat_raw_api_log
        SET source_id = 'lixinren'
        WHERE source_id = 'lixingren';

        UPDATE dat_fundamental_daily
        SET source_id = 'lixinren'
        WHERE source_id = 'lixingren';

        UPDATE dat_fund_daily
        SET source_id = 'lixinren'
        WHERE source_id = 'lixingren';

        UPDATE dat_data_quality_issue
        SET source_id = 'lixinren'
        WHERE source_id = 'lixingren';

        DELETE FROM sys_datasource
        WHERE source_id = 'lixingren'
          AND EXISTS (
              SELECT 1
              FROM sys_datasource
              WHERE source_id = 'lixinren'
          );

        UPDATE sys_datasource
        SET source_id = 'lixinren'
        WHERE source_id = 'lixingren';
        """
    )


def downgrade() -> None:
    """Data correction is intentionally irreversible."""
    pass
