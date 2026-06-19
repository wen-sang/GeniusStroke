from __future__ import annotations

from dataclasses import dataclass, field


class GapFillTaskStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FILLED = "FILLED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TdxRefreshStatus:
    SKIPPED_FRESH = "SKIPPED_FRESH"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    FAILED_SWITCH = "FAILED_SWITCH"
    LOCKED = "LOCKED"


class GapFillRunStatus:
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_DEFERRED = "COMPLETED_WITH_DEFERRED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    SKIPPED_TDX_NOT_READY = "SKIPPED_TDX_NOT_READY"
    SKIPPED_TDX_BUSY = "SKIPPED_TDX_BUSY"


class TdxFileStatus:
    READY = "ready"
    MISSING = "missing"
    INVALID = "invalid"


class TdxDateStatus:
    HIT = "hit"
    EMPTY = "empty"
    INVALID = "invalid"
    ZERO = "zero"


class TickFlowErrorCategory:
    AUTH_ERROR = "AUTH_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    SERVER_ERROR = "SERVER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class TickFlowDiscoveryStatus:
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GapFillConfirmationCode:
    OUTSIDE_SOURCE_COVERAGE = "CONFIRMED_OUTSIDE_SOURCE_COVERAGE"
    NO_SOURCE_BAR = "CONFIRMED_NO_SOURCE_BAR"
    ZERO_VOLUME_PLACEHOLDER = "CONFIRMED_ZERO_VOLUME_PLACEHOLDER"


class RepairStage:
    INDICATOR = "indicator"
    SNAPSHOT = "snapshot"
    ACCOUNT_HISTORY = "account_history"


@dataclass
class MarketGapFillResult:
    status: str = GapFillRunStatus.COMPLETED
    filled_codes: set[str] = field(default_factory=set)
    min_filled_date_by_code: dict[str, str] = field(default_factory=dict)
    filled_task_count: int = 0
    failed_task_count: int = 0
    skipped_task_count: int = 0
    deferred_task_count: int = 0
    generated_task_count: int = 0
    scan_batch_id: str | None = None
    account_history_rebuild: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    dry_run: bool = False
    preview_task_count: int = 0
    preview_tasks: list[dict] = field(default_factory=list)
    gate: dict = field(default_factory=lambda: {
        "status": "NOT_RUN",
        "package_id": None,
        "target_date": None,
        "max_trade_date": None,
        "skip_reason": None,
        "lock_wait_seconds": 0.0,
    })
    tdx: dict = field(default_factory=lambda: {
        "processed_assets": 0,
        "processed_tasks": 0,
        "filled_tasks": 0,
        "empty_tasks": 0,
        "zero_tasks": 0,
        "file_missing_assets": 0,
        "file_invalid_assets": 0,
        "health_breaker_triggered": False,
    })
    tickflow: dict = field(default_factory=lambda: {
        "enabled": False,
        "candidate_assets": 0,
        "requested_assets": 0,
        "filled_tasks": 0,
        "no_data_tasks": 0,
        "failed_tasks": 0,
        "budget_total": 0,
        "budget_remaining": 0,
        "deadline_reached": False,
        "breaker_triggered": False,
        "breaker_reason": None,
    })
    tasks: dict = field(default_factory=lambda: {
        "generated": 0,
        "claimed": 0,
        "processed": 0,
        "filled": 0,
        "confirmed": 0,
        "failed": 0,
        "skipped": 0,
        "deferred": 0,
        "lease_lost": 0,
    })
    history_discovery: dict = field(default_factory=lambda: {
        "tdx_processed_assets": 0,
        "tickflow_pending_assets": 0,
        "tickflow_completed_assets": 0,
        "tickflow_failed_assets": 0,
    })
    metadata_reconciliation: dict = field(default_factory=lambda: {
        "corrected_assets": 0,
        "conflict_assets": 0,
        "details": [],
    })
    downstream: dict = field(default_factory=lambda: {
        "claimed_assets": 0,
        "completed_assets": 0,
        "failed_assets": 0,
        "affected_accounts": 0,
        "failure_details": [],
    })
    timing: dict = field(default_factory=lambda: {
        "gate_seconds": 0.0,
        "scan_seconds": 0.0,
        "tdx_seconds": 0.0,
        "tickflow_seconds": 0.0,
        "downstream_seconds": 0.0,
        "total_seconds": 0.0,
    })

    def record_fill(self, asset_code: str, trade_date: str) -> None:
        self.filled_codes.add(asset_code)
        current = self.min_filled_date_by_code.get(asset_code)
        if current is None or trade_date < current:
            self.min_filled_date_by_code[asset_code] = trade_date
        self.filled_task_count += 1

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "filled_codes": sorted(self.filled_codes),
            "min_filled_date_by_code": dict(sorted(self.min_filled_date_by_code.items())),
            "filled_task_count": self.filled_task_count,
            "failed_task_count": self.failed_task_count,
            "skipped_task_count": self.skipped_task_count,
            "deferred_task_count": self.deferred_task_count,
            "generated_task_count": self.generated_task_count,
            "scan_batch_id": self.scan_batch_id,
            "account_history_rebuild": self.account_history_rebuild,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "preview_task_count": self.preview_task_count,
            "preview_tasks": self.preview_tasks,
            "gate": self.gate,
            "tdx": self.tdx,
            "tickflow": self.tickflow,
            "tasks": self.tasks,
            "history_discovery": self.history_discovery,
            "metadata_reconciliation": self.metadata_reconciliation,
            "downstream": self.downstream,
            "timing": self.timing,
        }


@dataclass(frozen=True)
class MarketGapFillRunOptions:
    asset_code: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    limit: int | None = None
    dry_run: bool = False
    no_external: bool = False
    force_tickflow_retry: bool = False

    def normalized_limit(self, default_limit: int) -> int:
        if self.limit is None:
            return default_limit
        return max(1, int(self.limit))
