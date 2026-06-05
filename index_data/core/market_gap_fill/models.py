from __future__ import annotations

from dataclasses import dataclass, field


class GapFillTaskStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FILLED = "FILLED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TdxRefreshStatus:
    SKIPPED_FRESH = "SKIPPED_FRESH"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    FAILED_SWITCH = "FAILED_SWITCH"


@dataclass
class MarketGapFillResult:
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

    def record_fill(self, asset_code: str, trade_date: str) -> None:
        self.filled_codes.add(asset_code)
        current = self.min_filled_date_by_code.get(asset_code)
        if current is None or trade_date < current:
            self.min_filled_date_by_code[asset_code] = trade_date
        self.filled_task_count += 1

    def to_dict(self) -> dict:
        return {
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
        }


@dataclass(frozen=True)
class MarketGapFillRunOptions:
    asset_code: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    limit: int | None = None
    dry_run: bool = False
    no_external: bool = False

    def normalized_limit(self, default_limit: int) -> int:
        if self.limit is None:
            return default_limit
        return max(1, int(self.limit))
