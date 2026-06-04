# core/database.py - Adapted for GeniusStroke v2.1
from sqlalchemy import create_engine

from core.db_engine import db_engine
from core.schema_metadata import metadata
from config.settings import DB_AUTO_SCHEMA, ENV
from utils.logger import logger

class DatabaseManager:
    """
    数据库初始化与维护工具类
    v2.6: 专注于 Schema 初始化与迁移，底层连接管理移交 db_engine
    """

    def init_db(self):
        """
        初始化数据库表结构 (v2.6 Schema)
        包含: 配置域、数据域、计算域
        """
        if not DB_AUTO_SCHEMA:
            logger.info(
                f"跳过数据库自动建表/补字段：DB_AUTO_SCHEMA=false (ENV={ENV})"
            )
            return

        logger.info(f"正在初始化数据库结构 (Target: {db_engine.db_path})...")

        try:
            self._create_schema_from_metadata()
            # 执行增量表结构变更 (ALTER TABLE)
            self._upgrade_schema_compat()
        except Exception as e:
            logger.critical(f"❌ 数据库初始化失败: {e}")
            raise e

    def _create_schema_from_metadata(self):
        """基于共享 metadata 建表，避免与 Alembic schema 定义漂移。"""
        engine = create_engine(f"sqlite:///{db_engine.db_path}")
        try:
            metadata.create_all(bind=engine, checkfirst=True)
            logger.info("✅ 数据库 v2.6 表结构初始化完成（来源: core.schema_metadata.metadata）。")
        finally:
            engine.dispose()
    
    def _upgrade_schema_compat(self):
        """
        增量迁移：补齐历史版本缺失字段/索引
        SQLite 的 ALTER TABLE 只支持 ADD COLUMN
        """
        alter_statements = [
            ("sys_data_router", "source_code", "TEXT"),
            ("sys_asset_meta", "market_category", "TEXT DEFAULT 'EXCHANGE'"),
            ("sys_asset_meta", "tags", "TEXT"),
            ("sys_asset_meta", "is_watchlist", "INTEGER DEFAULT 0"),
            ("sys_account_fund", "account_no", "TEXT"),
            ("sys_account_fund", "total_shares", "REAL DEFAULT 0"),
            ("trade_order", "order_no", "TEXT"),
            ("trade_order", "updated_at", "TEXT"),
            ("trade_order", "source_type", "TEXT"),
            ("trade_order", "source_ref_id", "TEXT"),
            ("trade_order", "order_type", "TEXT"),
            ("trade_order", "transfer_fee", "REAL DEFAULT 0"),
            ("account_cash_flow", "direction", "TEXT DEFAULT 'IN'"),
            ("account_cash_flow", "status", "TEXT DEFAULT 'ACTIVE'"),
            ("account_corporate_action", "confirmed_at", "TEXT"),
            ("account_corporate_action", "last_check_at", "TEXT"),
            ("account_corporate_action", "last_error_message", "TEXT"),
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
            ("dat_account_history", "daily_return_rate", "REAL"),
            ("dat_account_history", "cum_realized_pnl", "REAL"),
            ("dat_account_history", "cum_unrealized_pnl", "REAL"),
            ("dat_account_history", "cum_total_pnl", "REAL"),
            ("dat_account_history", "account_xirr", "REAL"),
            ("dat_account_history", "is_data_complete", "INTEGER DEFAULT 0"),
        ]
        
        with db_engine.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dat_realtime_quote_cache (
                        asset_code TEXT PRIMARY KEY,
                        asset_name TEXT,
                        price REAL,
                        high REAL,
                        low REAL,
                        volume REAL,
                        amount REAL,
                        amplitude REAL,
                        change_pct REAL,
                        change_amt REAL,
                        turnover REAL,
                        quote_date TEXT,
                        source TEXT,
                        is_realtime INTEGER DEFAULT 0,
                        refreshed_at TEXT DEFAULT (datetime('now', 'localtime')),
                        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                        created_at TEXT DEFAULT (datetime('now', 'localtime'))
                    )
                    """
                )
            except Exception as e:
                logger.warning(f"  ⚠️ 创建 dat_realtime_quote_cache 失败: {e}")

            for table, column, col_def in alter_statements:
                # 检查字段是否已存在
                cursor.execute(f"PRAGMA table_info({table})")
                existing_cols = [row[1] for row in cursor.fetchall()]
                
                if column not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                        logger.info(f"  ✅ 添加字段 {table}.{column}")
                    except Exception as e:
                        logger.warning(f"  ⚠️ 添加字段 {table}.{column} 失败: {e}")

            # 账户编号回填（仅对空值）
            try:
                cursor.execute("""
                    UPDATE sys_account_fund
                    SET account_no = 'ACC' || printf('%04d', account_id)
                    WHERE account_no IS NULL OR account_no = ''
                """)
            except Exception as e:
                logger.warning(f"  ⚠️ 回填 account_no 失败: {e}")

            try:
                cursor.execute("""
                    UPDATE trade_order
                    SET updated_at = COALESCE(updated_at, created_at, datetime('now', 'localtime'))
                    WHERE updated_at IS NULL OR updated_at = ''
                """)
            except Exception as e:
                logger.warning(f"  ⚠️ 回填 trade_order.updated_at 失败: {e}")

            try:
                cursor.execute(
                    """
                    UPDATE trade_order
                    SET order_type = CASE
                        WHEN COALESCE(source_type, '') = 'CORPORATE_ACTION' AND side = 'BUY' THEN 'DIVIDEND_REINVEST_BUY'
                        WHEN COALESCE(source_type, '') = 'CORPORATE_ACTION' AND side = 'ADJUST' THEN 'SPLIT_ADJUST'
                        WHEN side = 'BUY' THEN 'MANUAL_BUY'
                        WHEN side = 'SELL' THEN 'MANUAL_SELL'
                        ELSE order_type
                    END
                    WHERE order_type IS NULL OR order_type = ''
                    """
                )
            except Exception as e:
                logger.warning(f"  ⚠️ 回填 trade_order.order_type 失败: {e}")

            try:
                cursor.execute(
                    """
                    UPDATE account_cash_flow
                    SET status = 'ACTIVE'
                    WHERE status IS NULL OR status = ''
                    """
                )
            except Exception as e:
                logger.warning(f"  ⚠️ 回填 account_cash_flow.status 失败: {e}")

            try:
                cursor.execute(
                    """
                    UPDATE account_corporate_action
                    SET status = CASE
                        WHEN status = 'ACTIVE' THEN 'CONFIRMED'
                        ELSE status
                    END
                    WHERE status IN ('ACTIVE', 'CANCELLED')
                    """
                )
            except Exception as e:
                logger.warning(f"  ⚠️ 回填 account_corporate_action.status 失败: {e}")

            try:
                cursor.execute(
                    """
                    UPDATE account_corporate_action
                    SET confirmed_at = COALESCE(confirmed_at, updated_at, created_at, datetime('now', 'localtime'))
                    WHERE status = 'CONFIRMED' AND (confirmed_at IS NULL OR confirmed_at = '')
                    """
                )
            except Exception as e:
                logger.warning(f"  ⚠️ 回填 account_corporate_action.confirmed_at 失败: {e}")

            # 索引补齐
            index_sqls = [
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_account_no ON sys_account_fund(account_no)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_order_no ON trade_order(order_no)",
                "CREATE INDEX IF NOT EXISTS idx_position_account ON dat_position(account_id)",
                "CREATE INDEX IF NOT EXISTS idx_position_code ON dat_position(asset_code)",
                "CREATE INDEX IF NOT EXISTS idx_quote_cache_refreshed_at ON dat_realtime_quote_cache(refreshed_at)",
                "CREATE INDEX IF NOT EXISTS idx_cash_flow_account_date ON account_cash_flow(account_id, biz_date)",
                "CREATE INDEX IF NOT EXISTS idx_cash_flow_source ON account_cash_flow(source_type, source_ref_id)",
                "CREATE INDEX IF NOT EXISTS idx_corp_action_account_date ON account_corporate_action(account_id, effective_date DESC, action_id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_corp_action_asset_date ON account_corporate_action(account_id, asset_code, effective_date DESC, action_id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_corp_action_status ON account_corporate_action(account_id, status, effective_date DESC)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_order_corp_source_order_type ON trade_order(source_ref_id, order_type) WHERE source_type = 'CORPORATE_ACTION' AND source_ref_id IS NOT NULL AND status = 1",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_cash_flow_corp_source_flow_type ON account_cash_flow(source_ref_id, flow_type) WHERE source_type = 'CORPORATE_ACTION' AND source_ref_id IS NOT NULL AND COALESCE(status, 'ACTIVE') = 'ACTIVE'",
                # v2.6 补充索引
                "CREATE INDEX IF NOT EXISTS idx_trade_account_time ON trade_order(account_id, trade_time DESC)",
                "CREATE INDEX IF NOT EXISTS idx_indicator_date_code ON dat_indicator_daily(trade_date, asset_code)",
                "CREATE INDEX IF NOT EXISTS idx_fundamental_date_code ON dat_fundamental_daily(trade_date, asset_code)",
                "CREATE INDEX IF NOT EXISTS idx_market_date_code ON dat_market_daily(trade_date, asset_code)",
                "CREATE INDEX IF NOT EXISTS idx_router_interface_code_type_priority ON sys_data_router(interface, asset_code, asset_type, priority)"
            ]
            for sql in index_sqls:
                try:
                    cursor.execute(sql)
                except Exception as e:
                    logger.warning(f"  ⚠️ 创建索引失败: {sql} | {e}")

# 单例
db_manager = DatabaseManager()
