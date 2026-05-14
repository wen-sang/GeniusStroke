"""baseline_schema_v2_6

Revision ID: 9f4c2d7b1a6e
Revises: 56613cabb1ee
Create Date: 2026-03-06 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9f4c2d7b1a6e"
down_revision: Union[str, Sequence[str], None] = "56613cabb1ee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(connection, table_name: str, column_name: str) -> bool:
    rows = connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()
    raw_connection = connection.connection

    raw_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sys_datasource (
            source_id TEXT PRIMARY KEY,
            api_token TEXT,
            is_enable INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            extra_config TEXT
        );

        CREATE TABLE IF NOT EXISTS sys_asset_meta (
            asset_code TEXT PRIMARY KEY,
            asset_name TEXT NOT NULL,
            asset_type TEXT DEFAULT 'INDEX',
            exchange TEXT,
            listing_date TEXT,
            is_active INTEGER DEFAULT 1,
            market_category TEXT DEFAULT 'EXCHANGE',
            tags TEXT,
            is_watchlist INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sys_data_router (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_code TEXT,
            asset_type TEXT,
            interface TEXT NOT NULL,
            source_id TEXT,
            source_code TEXT,
            priority INTEGER DEFAULT 10,
            FOREIGN KEY (source_id) REFERENCES sys_datasource(source_id)
        );

        CREATE TABLE IF NOT EXISTS trade_calendar (
            trade_date TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS dat_raw_api_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT,
            asset_code TEXT,
            source_id TEXT,
            req_params TEXT,
            resp_payload BLOB NOT NULL,
            status INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS dat_market_daily (
            asset_code TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            source_id TEXT,
            updated_at TEXT,
            PRIMARY KEY (asset_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS sys_algo_meta (
            algo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            algo_name TEXT UNIQUE,
            lib_func TEXT NOT NULL,
            default_params TEXT,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS sys_algo_config (
            config_id INTEGER PRIMARY KEY AUTOINCREMENT,
            algo_id INTEGER,
            time_period TEXT DEFAULT '1d',
            params_json TEXT NOT NULL,
            params_hash TEXT UNIQUE,
            FOREIGN KEY (algo_id) REFERENCES sys_algo_meta(algo_id)
        );

        CREATE TABLE IF NOT EXISTS sys_algo_scope (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER,
            apply_target TEXT NOT NULL,
            is_enabled INTEGER DEFAULT 1,
            FOREIGN KEY (config_id) REFERENCES sys_algo_config(config_id)
        );

        CREATE TABLE IF NOT EXISTS dat_indicator_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            config_id INTEGER,
            val_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (config_id) REFERENCES sys_algo_config(config_id)
        );

        CREATE TABLE IF NOT EXISTS dat_fundamental_daily (
            asset_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            pe_ttm REAL,
            pb REAL,
            ps_ttm REAL,
            dyr REAL,
            pe_pos_fs REAL, pe_pos_10y REAL, pe_pos_5y REAL, pe_pos_3y REAL,
            pb_pos_fs REAL, pb_pos_10y REAL, pb_pos_5y REAL, pb_pos_3y REAL,
            ps_pos_fs REAL, ps_pos_10y REAL, ps_pos_5y REAL, ps_pos_3y REAL,
            dyr_pos_fs REAL, dyr_pos_10y REAL, dyr_pos_5y REAL, dyr_pos_3y REAL,
            full_stats_json TEXT,
            source_id TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (asset_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS sys_account_fund (
            account_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_no TEXT,
            account_name TEXT NOT NULL DEFAULT 'Default',
            broker_name TEXT,
            commission_rate REAL DEFAULT 0.00025,
            commission_min REAL DEFAULT 5.0,
            stamp_duty_rate REAL DEFAULT 0.001,
            cash_balance REAL DEFAULT 0,
            total_deposit REAL DEFAULT 0,
            total_withdraw REAL DEFAULT 0,
            total_shares REAL DEFAULT 0,
            acc_profit REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS trade_order (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT,
            account_id INTEGER DEFAULT 1,
            asset_code TEXT NOT NULL,
            trade_time TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            volume REAL NOT NULL,
            amount REAL NOT NULL,
            commission REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            remain_vol REAL DEFAULT 0,
            link_order_id INTEGER,
            target_rate REAL DEFAULT 0,
            realized_pnl REAL DEFAULT 0,
            status INTEGER DEFAULT 1,
            remark TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (account_id) REFERENCES sys_account_fund(account_id)
        );

        CREATE TABLE IF NOT EXISTS dat_fund_daily (
            asset_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            unit_nav REAL,
            accum_nav REAL,
            premium_rate REAL,
            source_id TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (asset_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS dat_position (
            account_id INTEGER NOT NULL,
            asset_code TEXT NOT NULL,
            total_volume REAL DEFAULT 0,
            available_volume REAL DEFAULT 0,
            cost_price REAL DEFAULT 0,
            cost_amount REAL DEFAULT 0,
            market_price REAL DEFAULT 0,
            market_value REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            pnl_ratio REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (account_id, asset_code)
        );

        CREATE TABLE IF NOT EXISTS dat_account_history (
            account_id INTEGER NOT NULL,
            trade_date TEXT NOT NULL,
            cash_balance REAL,
            market_value REAL,
            total_asset REAL,
            total_deposit REAL,
            total_withdraw REAL,
            total_shares REAL,
            unit_net_value REAL,
            daily_return REAL,
            net_investment REAL,
            total_pnl REAL,
            pnl_ratio REAL,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (account_id, trade_date),
            FOREIGN KEY (account_id) REFERENCES sys_account_fund(account_id)
        );

        CREATE TABLE IF NOT EXISTS log_trade_audit (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            order_id INTEGER,
            action_type TEXT NOT NULL,
            before_cash REAL,
            after_cash REAL,
            amount_change REAL,
            before_deposit REAL,
            after_deposit REAL,
            before_withdraw REAL,
            after_withdraw REAL,
            before_profit REAL,
            after_profit REAL,
            snapshot_json TEXT,
            remark TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (account_id) REFERENCES sys_account_fund(account_id)
        );
        """
    )

    alter_statements = [
        ("sys_data_router", "source_code", "TEXT"),
        ("sys_asset_meta", "market_category", "TEXT DEFAULT 'EXCHANGE'"),
        ("sys_asset_meta", "tags", "TEXT"),
        ("sys_asset_meta", "is_watchlist", "INTEGER DEFAULT 0"),
        ("sys_account_fund", "account_no", "TEXT"),
        ("sys_account_fund", "total_shares", "REAL DEFAULT 0"),
        ("trade_order", "order_no", "TEXT"),
        ("trade_order", "updated_at", "TEXT"),
        ("log_trade_audit", "before_deposit", "REAL"),
        ("log_trade_audit", "after_deposit", "REAL"),
        ("log_trade_audit", "before_withdraw", "REAL"),
        ("log_trade_audit", "after_withdraw", "REAL"),
        ("log_trade_audit", "before_profit", "REAL"),
        ("log_trade_audit", "after_profit", "REAL"),
        ("log_trade_audit", "snapshot_json", "TEXT"),
        ("dat_account_history", "cash_balance", "REAL"),
        ("dat_account_history", "market_value", "REAL"),
        ("dat_account_history", "total_deposit", "REAL"),
        ("dat_account_history", "total_withdraw", "REAL"),
        ("dat_account_history", "net_investment", "REAL"),
        ("dat_account_history", "total_pnl", "REAL"),
        ("dat_account_history", "pnl_ratio", "REAL"),
        ("dat_account_history", "total_shares", "REAL"),
    ]

    for table_name, column_name, column_def in alter_statements:
        if not _has_column(connection, table_name, column_name):
            connection.exec_driver_sql(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
            )

    connection.exec_driver_sql(
        """
        UPDATE sys_account_fund
        SET account_no = 'ACC' || printf('%04d', account_id)
        WHERE account_no IS NULL OR account_no = '';
        """
    )
    connection.exec_driver_sql(
        """
        UPDATE trade_order
        SET updated_at = COALESCE(updated_at, created_at, datetime('now', 'localtime'))
        WHERE updated_at IS NULL OR updated_at = '';
        """
    )

    index_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_raw_status ON dat_raw_api_log(status)",
        "CREATE INDEX IF NOT EXISTS idx_raw_code ON dat_raw_api_log(asset_code)",
        "CREATE INDEX IF NOT EXISTS idx_scope_target ON sys_algo_scope(apply_target)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_indicator_u1 ON dat_indicator_daily(asset_code, trade_date, config_id)",
        "CREATE INDEX IF NOT EXISTS idx_fund_code_date ON dat_fundamental_daily(asset_code, trade_date)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_account_no ON sys_account_fund(account_no)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_order_no ON trade_order(order_no)",
        "CREATE INDEX IF NOT EXISTS idx_trade_code ON trade_order(asset_code)",
        "CREATE INDEX IF NOT EXISTS idx_trade_remain ON trade_order(remain_vol) WHERE remain_vol > 0",
        "CREATE INDEX IF NOT EXISTS idx_trade_account ON trade_order(account_id)",
        "CREATE INDEX IF NOT EXISTS idx_position_account ON dat_position(account_id)",
        "CREATE INDEX IF NOT EXISTS idx_position_code ON dat_position(asset_code)",
        "CREATE INDEX IF NOT EXISTS idx_audit_account ON log_trade_audit(account_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_time ON log_trade_audit(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_trade_account_time ON trade_order(account_id, trade_time DESC)",
        "CREATE INDEX IF NOT EXISTS idx_indicator_date_code ON dat_indicator_daily(trade_date, asset_code)",
        "CREATE INDEX IF NOT EXISTS idx_fundamental_date_code ON dat_fundamental_daily(trade_date, asset_code)",
        "CREATE INDEX IF NOT EXISTS idx_market_date_code ON dat_market_daily(trade_date, asset_code)",
        "CREATE INDEX IF NOT EXISTS idx_router_interface_code_type_priority ON sys_data_router(interface, asset_code, asset_type, priority)",
    ]
    for index_sql in index_sqls:
        connection.exec_driver_sql(index_sql)


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "Baseline schema migration is not safely reversible on SQLite."
    )
