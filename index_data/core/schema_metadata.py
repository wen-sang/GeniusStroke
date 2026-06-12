from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    REAL,
    Table,
    Text,
    UniqueConstraint,
    text,
)


metadata = MetaData()

_LOCAL_NOW = text("(datetime('now', 'localtime'))")


sys_datasource = Table(
    "sys_datasource",
    metadata,
    Column("source_id", Text, primary_key=True),
    Column("api_token", Text),
    Column("is_enable", Integer, server_default=text("1")),
    Column("priority", Integer, server_default=text("0")),
    Column("extra_config", Text),
)

sys_asset_meta = Table(
    "sys_asset_meta",
    metadata,
    Column("asset_code", Text, primary_key=True),
    Column("asset_name", Text, nullable=False),
    Column("asset_type", Text, server_default=text("'INDEX'")),
    Column("exchange", Text),
    Column("listing_date", Text),
    Column("is_active", Integer, server_default=text("1")),
    Column("market_category", Text, server_default=text("'EXCHANGE'")),
    Column("tags", Text),
    Column("is_watchlist", Integer, server_default=text("0")),
)

sys_data_router = Table(
    "sys_data_router",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("asset_code", Text),
    Column("asset_type", Text),
    Column("interface", Text, nullable=False),
    Column("source_id", Text, ForeignKey("sys_datasource.source_id")),
    Column("source_code", Text),
    Column("priority", Integer, server_default=text("10")),
)
Index(
    "idx_router_interface_code_type_priority",
    sys_data_router.c.interface,
    sys_data_router.c.asset_code,
    sys_data_router.c.asset_type,
    sys_data_router.c.priority,
)

trade_calendar = Table(
    "trade_calendar",
    metadata,
    Column("trade_date", Text, primary_key=True),
)

trade_calendar_exchange = Table(
    "trade_calendar_exchange",
    metadata,
    Column("exchange", Text, primary_key=True),
    Column("calendar_date", Text, primary_key=True),
    Column("is_open", Integer, nullable=False),
    Column("updated_at", Text, nullable=False),
    CheckConstraint(
        "exchange IN ('SH', 'SZ', 'HK')",
        name="ck_trade_calendar_exchange_exchange",
    ),
    CheckConstraint(
        "is_open IN (0, 1)",
        name="ck_trade_calendar_exchange_is_open",
    ),
)
Index(
    "idx_trade_calendar_exchange_open_date",
    trade_calendar_exchange.c.exchange,
    trade_calendar_exchange.c.is_open,
    trade_calendar_exchange.c.calendar_date,
)

dat_raw_api_log = Table(
    "dat_raw_api_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", Text),
    Column("asset_code", Text),
    Column("source_id", Text),
    Column("req_params", Text),
    Column("resp_payload", LargeBinary, nullable=False),
    Column("status", Integer, server_default=text("0")),
    Column("created_at", Text, server_default=_LOCAL_NOW),
)
Index("idx_raw_status", dat_raw_api_log.c.status)
Index("idx_raw_code", dat_raw_api_log.c.asset_code)

dat_external_asset_catalog = Table(
    "dat_external_asset_catalog",
    metadata,
    Column("catalog_id", Integer, primary_key=True, autoincrement=True),
    Column("source_id", Text, nullable=False),
    Column("external_symbol", Text, nullable=False),
    Column("asset_code", Text, nullable=False),
    Column("asset_name", Text, nullable=False),
    Column("asset_type", Text, nullable=False),
    Column("exchange", Text),
    Column("market_category", Text, nullable=False, server_default=text("'EXCHANGE'")),
    Column("listing_date", Text),
    Column("source_universe_id", Text),
    Column("source_universe_name", Text),
    Column("source_asset_type", Text),
    Column("source_status", Text),
    Column("raw_payload", Text, nullable=False),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("first_seen_at", Text, nullable=False, server_default=_LOCAL_NOW),
    Column("last_synced_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False, server_default=_LOCAL_NOW),
    UniqueConstraint("source_id", "external_symbol", name="uq_external_catalog_source_symbol"),
)
Index(
    "idx_external_catalog_source_type_exchange",
    dat_external_asset_catalog.c.source_id,
    dat_external_asset_catalog.c.asset_type,
    dat_external_asset_catalog.c.exchange,
    dat_external_asset_catalog.c.is_active,
)
Index(
    "idx_external_catalog_code_exchange",
    dat_external_asset_catalog.c.asset_code,
    dat_external_asset_catalog.c.exchange,
)
Index("idx_external_catalog_name", dat_external_asset_catalog.c.asset_name)
Index(
    "idx_external_catalog_sync",
    dat_external_asset_catalog.c.source_id,
    dat_external_asset_catalog.c.is_active,
    dat_external_asset_catalog.c.last_synced_at,
)

dat_external_asset_catalog_sync_log = Table(
    "dat_external_asset_catalog_sync_log",
    metadata,
    Column("sync_id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("total_fetched", Integer, nullable=False, server_default=text("0")),
    Column("total_upserted", Integer, nullable=False, server_default=text("0")),
    Column("total_deactivated", Integer, nullable=False, server_default=text("0")),
    Column("deactivation_skipped", Integer, nullable=False, server_default=text("0")),
    Column("skip_reason", Text),
    Column("error_message", Text),
)
Index(
    "idx_external_catalog_sync_log_source_started",
    dat_external_asset_catalog_sync_log.c.source_id,
    dat_external_asset_catalog_sync_log.c.started_at,
)

dat_market_daily = Table(
    "dat_market_daily",
    metadata,
    Column("asset_code", Text, primary_key=True),
    Column("trade_date", Text, primary_key=True),
    Column("open", REAL),
    Column("high", REAL),
    Column("low", REAL),
    Column("close", REAL),
    Column("volume", REAL),
    Column("amount", REAL),
    Column("source_id", Text),
    Column("updated_at", Text),
)
Index("idx_market_date_code", dat_market_daily.c.trade_date, dat_market_daily.c.asset_code)
Index(
    "idx_market_date_amount_code",
    dat_market_daily.c.trade_date,
    dat_market_daily.c.amount,
    dat_market_daily.c.asset_code,
)

dat_market_return_snapshot = Table(
    "dat_market_return_snapshot",
    metadata,
    Column("asset_code", Text, primary_key=True),
    Column("trade_date", Text, primary_key=True),
    Column("return_22d", REAL),
    Column("return_60d", REAL),
    Column("return_6m", REAL),
    Column("return_1y", REAL),
    Column("updated_at", Text, nullable=False, server_default=_LOCAL_NOW),
)
Index(
    "idx_market_return_snapshot_date_code",
    dat_market_return_snapshot.c.trade_date,
    dat_market_return_snapshot.c.asset_code,
)
Index(
    "idx_market_return_snapshot_date_22d",
    dat_market_return_snapshot.c.trade_date,
    dat_market_return_snapshot.c.return_22d,
)
Index(
    "idx_market_return_snapshot_date_60d",
    dat_market_return_snapshot.c.trade_date,
    dat_market_return_snapshot.c.return_60d,
)
Index(
    "idx_market_return_snapshot_date_6m",
    dat_market_return_snapshot.c.trade_date,
    dat_market_return_snapshot.c.return_6m,
)
Index(
    "idx_market_return_snapshot_date_1y",
    dat_market_return_snapshot.c.trade_date,
    dat_market_return_snapshot.c.return_1y,
)

dat_data_quality_scan_batch = Table(
    "dat_data_quality_scan_batch",
    metadata,
    Column("scan_batch_id", Text, primary_key=True),
    Column("source_table", Text, nullable=False),
    Column("trigger_type", Text, nullable=False),
    Column("scan_scope", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("scanned_rows", Integer, nullable=False, server_default=text("0")),
    Column("issue_count", Integer, nullable=False, server_default=text("0")),
    Column("report_path", Text),
    Column("error_message", Text),
    CheckConstraint(
        "source_table IN ('dat_market_daily')",
        name="ck_quality_scan_batch_source_table",
    ),
    CheckConstraint(
        "trigger_type IN ('MANUAL', 'DAILY_JOB')",
        name="ck_quality_scan_batch_trigger_type",
    ),
    CheckConstraint(
        "scan_scope IN ('FULL', 'INCREMENTAL')",
        name="ck_quality_scan_batch_scan_scope",
    ),
    CheckConstraint(
        "status IN ('RUNNING', 'SUCCESS', 'FAILED')",
        name="ck_quality_scan_batch_status",
    ),
)
Index(
    "idx_quality_scan_batch_status_started",
    dat_data_quality_scan_batch.c.status,
    dat_data_quality_scan_batch.c.started_at,
)

dat_data_quality_issue = Table(
    "dat_data_quality_issue",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "scan_batch_id",
        Text,
        ForeignKey("dat_data_quality_scan_batch.scan_batch_id"),
        nullable=False,
    ),
    Column("asset_code", Text),
    Column("trade_date", Text),
    Column("source_table", Text, nullable=False),
    Column("source_id", Text),
    Column("entity_type", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("rule_code", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("issue_group", Text, nullable=False),
    Column("field_name", Text),
    Column("actual_value", Text),
    Column("expected_value", Text),
    Column("detail_json", Text, nullable=False),
    Column("issue_status", Text, nullable=False),
    Column("detected_at", Text, nullable=False),
    CheckConstraint(
        "severity IN ('ERROR', 'WARN', 'CANDIDATE')",
        name="ck_quality_issue_severity",
    ),
    CheckConstraint(
        "issue_group IN ('META', 'CALENDAR', 'OHLC', "
        "'VOLUME_AMOUNT', 'CONTINUITY')",
        name="ck_quality_issue_group",
    ),
    CheckConstraint(
        "issue_status IN ('OPEN', 'IGNORED', 'CONFIRMED', 'FIXED')",
        name="ck_quality_issue_status",
    ),
    CheckConstraint(
        "entity_type IN ('MARKET_ROW', 'ASSET', 'EXCHANGE', "
        "'CALENDAR_DATE')",
        name="ck_quality_issue_entity_type",
    ),
)
Index("idx_quality_issue_batch", dat_data_quality_issue.c.scan_batch_id)
Index(
    "idx_quality_issue_asset_date",
    dat_data_quality_issue.c.asset_code,
    dat_data_quality_issue.c.trade_date,
)
Index("idx_quality_issue_rule", dat_data_quality_issue.c.rule_code)
Index("idx_quality_issue_status", dat_data_quality_issue.c.issue_status)
Index("idx_quality_issue_source", dat_data_quality_issue.c.source_id)
Index(
    "idx_quality_issue_entity",
    dat_data_quality_issue.c.entity_type,
    dat_data_quality_issue.c.entity_id,
)
Index(
    "uq_quality_issue_batch_key",
    dat_data_quality_issue.c.scan_batch_id,
    dat_data_quality_issue.c.source_table,
    dat_data_quality_issue.c.entity_type,
    text("COALESCE(entity_id, '')"),
    text("COALESCE(asset_code, '')"),
    text("COALESCE(trade_date, '')"),
    dat_data_quality_issue.c.rule_code,
    text("COALESCE(field_name, '')"),
    unique=True,
)

dat_market_gap_fill_task = Table(
    "dat_market_gap_fill_task",
    metadata,
    Column("task_id", Integer, primary_key=True, autoincrement=True),
    Column("asset_code", Text, nullable=False),
    Column("missing_date", Text, nullable=False),
    Column("exchange", Text),
    Column("asset_type", Text),
    Column("route_source_id", Text),
    Column("route_source_code", Text),
    Column("latest_issue_id", Integer, ForeignKey("dat_data_quality_issue.id")),
    Column("status", Text, nullable=False, server_default=text("'PENDING'")),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("max_attempts", Integer, nullable=False, server_default=text("3")),
    Column("next_retry_at", Text),
    Column("run_id", Text),
    Column("claimed_at", Text),
    Column("claim_expires_at", Text),
    Column("filled_source_id", Text),
    Column("filled_at", Text),
    Column("last_error_code", Text),
    Column("last_error_message", Text),
    Column("last_tdx_package_id", Text),
    Column("last_tickflow_catalog_version", Text),
    Column("last_tickflow_config_signature", Text),
    Column("tickflow_retry_after", Text),
    Column("detail_json", Text, nullable=False, server_default=text("'{}'")),
    Column("created_at", Text, nullable=False, server_default=_LOCAL_NOW),
    Column("updated_at", Text, nullable=False, server_default=_LOCAL_NOW),
    CheckConstraint(
        "status IN ('PENDING', 'RUNNING', 'FILLED', 'FAILED', 'SKIPPED')",
        name="ck_market_gap_fill_task_status",
    ),
    UniqueConstraint(
        "asset_code",
        "missing_date",
        name="uq_market_gap_fill_task_asset_date",
    ),
)
Index(
    "idx_market_gap_fill_task_status_retry",
    dat_market_gap_fill_task.c.status,
    dat_market_gap_fill_task.c.next_retry_at,
)
Index(
    "idx_market_gap_fill_task_asset_status",
    dat_market_gap_fill_task.c.exchange,
    dat_market_gap_fill_task.c.asset_code,
    dat_market_gap_fill_task.c.status,
    dat_market_gap_fill_task.c.missing_date,
)
Index(
    "idx_market_gap_fill_task_issue",
    dat_market_gap_fill_task.c.latest_issue_id,
)
Index(
    "idx_market_gap_fill_task_claim",
    dat_market_gap_fill_task.c.run_id,
    dat_market_gap_fill_task.c.claim_expires_at,
)

dat_market_gap_fill_asset_state = Table(
    "dat_market_gap_fill_asset_state",
    metadata,
    Column("asset_code", Text, primary_key=True),
    Column("target_start_date", Text, nullable=False),
    Column("earliest_generated_date", Text),
    Column("updated_at", Text, nullable=False, server_default=_LOCAL_NOW),
)

dat_market_gap_fill_repair_task = Table(
    "dat_market_gap_fill_repair_task",
    metadata,
    Column("repair_id", Integer, primary_key=True, autoincrement=True),
    Column("asset_code", Text, nullable=False, unique=True),
    Column("from_date", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'PENDING'")),
    Column("generation", Integer, nullable=False, server_default=text("1")),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("last_attempt_sync_id", Text),
    Column("run_id", Text),
    Column("claimed_at", Text),
    Column("claim_expires_at", Text),
    Column("last_failed_stage", Text),
    Column("last_error_code", Text),
    Column("last_error_message", Text),
    Column("detail_json", Text, nullable=False, server_default=text("'{}'")),
    Column("completed_at", Text),
    Column("created_at", Text, nullable=False, server_default=_LOCAL_NOW),
    Column("updated_at", Text, nullable=False, server_default=_LOCAL_NOW),
    CheckConstraint(
        "status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')",
        name="ck_market_gap_fill_repair_task_status",
    ),
)
Index(
    "idx_market_gap_fill_repair_status_sync",
    dat_market_gap_fill_repair_task.c.status,
    dat_market_gap_fill_repair_task.c.last_attempt_sync_id,
)
Index(
    "idx_market_gap_fill_repair_claim",
    dat_market_gap_fill_repair_task.c.run_id,
    dat_market_gap_fill_repair_task.c.claim_expires_at,
)

dat_tickflow_gap_fill_runtime = Table(
    "dat_tickflow_gap_fill_runtime",
    metadata,
    Column("runtime_id", Integer, primary_key=True),
    Column("last_request_started_at", Text),
    Column("breaker_state", Text, nullable=False, server_default=text("'CLOSED'")),
    Column("breaker_reason", Text),
    Column("breaker_until", Text),
    Column("breaker_config_signature", Text),
    Column("consecutive_error_count", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", Text, nullable=False, server_default=_LOCAL_NOW),
    CheckConstraint(
        "runtime_id = 1",
        name="ck_tickflow_gap_fill_runtime_singleton",
    ),
    CheckConstraint(
        "breaker_state IN ('CLOSED', 'OPEN')",
        name="ck_tickflow_gap_fill_runtime_breaker_state",
    ),
)

sys_algo_meta = Table(
    "sys_algo_meta",
    metadata,
    Column("algo_id", Integer, primary_key=True, autoincrement=True),
    Column("algo_name", Text, unique=True),
    Column("lib_func", Text, nullable=False),
    Column("default_params", Text),
    Column("description", Text),
)

sys_algo_config = Table(
    "sys_algo_config",
    metadata,
    Column("config_id", Integer, primary_key=True, autoincrement=True),
    Column("algo_id", Integer, ForeignKey("sys_algo_meta.algo_id")),
    Column("time_period", Text, server_default=text("'1d'")),
    Column("params_json", Text, nullable=False),
    Column("params_hash", Text, unique=True),
)

sys_algo_scope = Table(
    "sys_algo_scope",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("config_id", Integer, ForeignKey("sys_algo_config.config_id")),
    Column("apply_target", Text, nullable=False),
    Column("is_enabled", Integer, server_default=text("1")),
)
Index("idx_scope_target", sys_algo_scope.c.apply_target)

dat_indicator_daily = Table(
    "dat_indicator_daily",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("asset_code", Text, nullable=False),
    Column("trade_date", Text, nullable=False),
    Column("config_id", Integer, ForeignKey("sys_algo_config.config_id")),
    Column("val_json", Text, nullable=False),
    Column("created_at", Text, server_default=_LOCAL_NOW),
)
Index(
    "idx_indicator_u1",
    dat_indicator_daily.c.asset_code,
    dat_indicator_daily.c.trade_date,
    dat_indicator_daily.c.config_id,
    unique=True,
)
Index(
    "idx_indicator_date_code",
    dat_indicator_daily.c.trade_date,
    dat_indicator_daily.c.asset_code,
)

dat_fundamental_daily = Table(
    "dat_fundamental_daily",
    metadata,
    Column("asset_code", Text, primary_key=True),
    Column("trade_date", Text, primary_key=True),
    Column("pe_ttm", REAL),
    Column("pb", REAL),
    Column("ps_ttm", REAL),
    Column("dyr", REAL),
    Column("pe_pos_fs", REAL),
    Column("pe_pos_10y", REAL),
    Column("pe_pos_5y", REAL),
    Column("pe_pos_3y", REAL),
    Column("pb_pos_fs", REAL),
    Column("pb_pos_10y", REAL),
    Column("pb_pos_5y", REAL),
    Column("pb_pos_3y", REAL),
    Column("ps_pos_fs", REAL),
    Column("ps_pos_10y", REAL),
    Column("ps_pos_5y", REAL),
    Column("ps_pos_3y", REAL),
    Column("dyr_pos_fs", REAL),
    Column("dyr_pos_10y", REAL),
    Column("dyr_pos_5y", REAL),
    Column("dyr_pos_3y", REAL),
    Column("full_stats_json", Text),
    Column("source_id", Text),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
)
Index(
    "idx_fund_code_date",
    dat_fundamental_daily.c.asset_code,
    dat_fundamental_daily.c.trade_date,
)
Index(
    "idx_fundamental_date_code",
    dat_fundamental_daily.c.trade_date,
    dat_fundamental_daily.c.asset_code,
)

sys_account_fund = Table(
    "sys_account_fund",
    metadata,
    Column("account_id", Integer, primary_key=True, autoincrement=True),
    Column("account_no", Text),
    Column("account_name", Text, nullable=False, server_default=text("'Default'")),
    Column("broker_name", Text),
    Column("commission_rate", REAL, server_default=text("0.00025")),
    Column("commission_min", REAL, server_default=text("5.0")),
    Column("stamp_duty_rate", REAL, server_default=text("0.001")),
    Column("cash_balance", REAL, server_default=text("0")),
    Column("total_deposit", REAL, server_default=text("0")),
    Column("total_withdraw", REAL, server_default=text("0")),
    Column("total_shares", REAL, server_default=text("0")),
    Column("acc_profit", REAL, server_default=text("0")),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
)
Index("idx_account_no", sys_account_fund.c.account_no, unique=True)

account_cash_flow = Table(
    "account_cash_flow",
    metadata,
    Column("flow_id", Integer, primary_key=True, autoincrement=True),
    Column("account_id", Integer, ForeignKey("sys_account_fund.account_id"), nullable=False),
    Column("biz_date", Text, nullable=False),
    Column("flow_type", Text, nullable=False),
    Column("direction", Text, nullable=False, server_default=text("'IN'")),
    Column("amount", REAL, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'ACTIVE'")),
    Column("remark", Text),
    Column("source_type", Text),
    Column("source_ref_id", Text),
    Column("created_at", Text, server_default=_LOCAL_NOW),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
)
Index("idx_cash_flow_account_date", account_cash_flow.c.account_id, account_cash_flow.c.biz_date)
Index("idx_cash_flow_source", account_cash_flow.c.source_type, account_cash_flow.c.source_ref_id)

account_corporate_action = Table(
    "account_corporate_action",
    metadata,
    Column("action_id", Integer, primary_key=True, autoincrement=True),
    Column("account_id", Integer, ForeignKey("sys_account_fund.account_id"), nullable=False),
    Column("asset_code", Text, nullable=False),
    Column("action_type", Text, nullable=False),
    Column("effective_date", Text, nullable=False),
    Column("record_date", Text),
    Column("ex_date", Text),
    Column("cash_base_unit", Text),
    Column("cash_base_qty", REAL),
    Column("cash_amount", REAL),
    Column("ratio_from", Integer),
    Column("ratio_to", Integer),
    Column("share_change_subtype", Text),
    Column("tax_mode", Text),
    Column("bundle_ref_id", Text),
    Column("reinvest_price", REAL),
    Column("rounding_policy", Text),
    Column("status", Text, nullable=False, server_default=text("'PENDING'")),
    Column("remark", Text),
    Column("source_type", Text, nullable=False, server_default=text("'MANUAL'")),
    Column("source_ref_id", Text),
    Column("confirmed_at", Text),
    Column("last_check_at", Text),
    Column("last_error_message", Text),
    Column("created_at", Text, server_default=_LOCAL_NOW),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
)
Index(
    "idx_corp_action_account_date",
    account_corporate_action.c.account_id,
    account_corporate_action.c.effective_date.desc(),
    account_corporate_action.c.action_id.desc(),
)
Index(
    "idx_corp_action_asset_date",
    account_corporate_action.c.account_id,
    account_corporate_action.c.asset_code,
    account_corporate_action.c.effective_date.desc(),
    account_corporate_action.c.action_id.desc(),
)
Index(
    "idx_corp_action_status",
    account_corporate_action.c.account_id,
    account_corporate_action.c.status,
    account_corporate_action.c.effective_date.desc(),
)
Index("idx_corp_action_bundle_ref", account_corporate_action.c.bundle_ref_id)
Index(
    "idx_corp_action_account_bundle",
    account_corporate_action.c.account_id,
    account_corporate_action.c.bundle_ref_id,
)
Index(
    "idx_corp_action_asset_record_ex",
    account_corporate_action.c.account_id,
    account_corporate_action.c.asset_code,
    account_corporate_action.c.record_date,
    account_corporate_action.c.ex_date,
)
Index(
    "idx_cash_flow_dividend_tax_source",
    account_cash_flow.c.source_type,
    account_cash_flow.c.source_ref_id,
    account_cash_flow.c.flow_type,
)

trade_order = Table(
    "trade_order",
    metadata,
    Column("order_id", Integer, primary_key=True, autoincrement=True),
    Column("order_no", Text),
    Column("account_id", Integer, ForeignKey("sys_account_fund.account_id"), server_default=text("1")),
    Column("asset_code", Text, nullable=False),
    Column("trade_time", Text, nullable=False),
    Column("side", Text, nullable=False),
    Column("order_type", Text),
    Column("price", REAL, nullable=False),
    Column("volume", REAL, nullable=False),
    Column("amount", REAL, nullable=False),
    Column("commission", REAL, server_default=text("0")),
    Column("transfer_fee", REAL, server_default=text("0")),
    Column("tax", REAL, server_default=text("0")),
    Column("remain_vol", REAL, server_default=text("0")),
    Column("link_order_id", Integer),
    Column("target_rate", REAL, server_default=text("0")),
    Column("realized_pnl", REAL, server_default=text("0")),
    Column("status", Integer, server_default=text("1")),
    Column("remark", Text),
    Column("source_type", Text),
    Column("source_ref_id", Text),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
    Column("created_at", Text, server_default=_LOCAL_NOW),
)
Index("idx_order_no", trade_order.c.order_no, unique=True)
Index("idx_trade_code", trade_order.c.asset_code)
Index("idx_trade_account", trade_order.c.account_id)
Index(
    "idx_trade_remain",
    trade_order.c.remain_vol,
    sqlite_where=trade_order.c.remain_vol > 0,
)
Index(
    "idx_trade_account_time",
    trade_order.c.account_id,
    trade_order.c.trade_time.desc(),
)
Index(
    "uq_trade_order_manual_source_ref",
    trade_order.c.account_id,
    trade_order.c.source_ref_id,
    unique=True,
    sqlite_where=(
        (trade_order.c.source_type == "MANUAL")
        & (trade_order.c.source_ref_id.isnot(None))
        & (trade_order.c.status == 1)
    ),
)

dat_fund_daily = Table(
    "dat_fund_daily",
    metadata,
    Column("asset_code", Text, primary_key=True),
    Column("trade_date", Text, primary_key=True),
    Column("unit_nav", REAL),
    Column("accum_nav", REAL),
    Column("premium_rate", REAL),
    Column("source_id", Text),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
)

dat_position = Table(
    "dat_position",
    metadata,
    Column("account_id", Integer, primary_key=True),
    Column("asset_code", Text, primary_key=True),
    Column("total_volume", REAL, server_default=text("0")),
    Column("available_volume", REAL, server_default=text("0")),
    Column("cost_price", REAL, server_default=text("0")),
    Column("cost_amount", REAL, server_default=text("0")),
    Column("market_price", REAL, server_default=text("0")),
    Column("market_value", REAL, server_default=text("0")),
    Column("unrealized_pnl", REAL, server_default=text("0")),
    Column("pnl_ratio", REAL, server_default=text("0")),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
)
Index("idx_position_account", dat_position.c.account_id)
Index("idx_position_code", dat_position.c.asset_code)

dat_realtime_quote_cache = Table(
    "dat_realtime_quote_cache",
    metadata,
    Column("asset_code", Text, primary_key=True),
    Column("asset_name", Text),
    Column("price", REAL),
    Column("high", REAL),
    Column("low", REAL),
    Column("volume", REAL),
    Column("amount", REAL),
    Column("amplitude", REAL),
    Column("change_pct", REAL),
    Column("change_amt", REAL),
    Column("turnover", REAL),
    Column("quote_date", Text),
    Column("source", Text),
    Column("is_realtime", Integer, server_default=text("0")),
    Column("refreshed_at", Text, server_default=_LOCAL_NOW),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
    Column("created_at", Text, server_default=_LOCAL_NOW),
)
Index("idx_quote_cache_refreshed_at", dat_realtime_quote_cache.c.refreshed_at)

dat_account_history = Table(
    "dat_account_history",
    metadata,
    Column("account_id", Integer, ForeignKey("sys_account_fund.account_id"), primary_key=True),
    Column("trade_date", Text, primary_key=True),
    Column("cash_balance", REAL),
    Column("market_value", REAL),
    Column("total_asset", REAL),
    Column("total_deposit", REAL),
    Column("total_withdraw", REAL),
    Column("total_shares", REAL),
    Column("unit_net_value", REAL),
    Column("daily_return", REAL),
    Column("daily_return_rate", REAL),
    Column("net_investment", REAL),
    Column("total_pnl", REAL),
    Column("pnl_ratio", REAL),
    Column("cum_realized_pnl", REAL),
    Column("cum_unrealized_pnl", REAL),
    Column("cum_total_pnl", REAL),
    Column("account_xirr", REAL),
    Column("is_data_complete", Integer, server_default=text("0")),
    Column("updated_at", Text, server_default=_LOCAL_NOW),
)

log_trade_audit = Table(
    "log_trade_audit",
    metadata,
    Column("log_id", Integer, primary_key=True, autoincrement=True),
    Column("account_id", Integer, ForeignKey("sys_account_fund.account_id"), nullable=False),
    Column("order_id", Integer),
    Column("action_type", Text, nullable=False),
    Column("before_cash", REAL),
    Column("after_cash", REAL),
    Column("amount_change", REAL),
    Column("before_deposit", REAL),
    Column("after_deposit", REAL),
    Column("before_withdraw", REAL),
    Column("after_withdraw", REAL),
    Column("before_profit", REAL),
    Column("after_profit", REAL),
    Column("snapshot_json", Text),
    Column("remark", Text),
    Column("created_at", Text, server_default=_LOCAL_NOW),
)
Index("idx_audit_account", log_trade_audit.c.account_id)
Index("idx_audit_time", log_trade_audit.c.created_at)
