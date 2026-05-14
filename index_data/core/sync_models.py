from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

TOTAL_SYNC_STEPS = 4


class SyncTaskStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class SyncStepLifecycle(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SyncStep:
    number: int
    name: str


SYNC_STEPS: tuple[SyncStep, ...] = (
    SyncStep(1, "环境检查"),
    SyncStep(2, "数据采集"),
    SyncStep(3, "指标计算"),
    SyncStep(4, "资产刷新"),
)

SYNC_STEP_MAP = {step.number: step for step in SYNC_STEPS}


StepChangeCallback = Callable[[int, str, str], None]
ProgressCallback = Callable[[int, Optional[int], Optional[str], Optional[str]], None]
LogCallback = Callable[[str, str, Optional[str], Optional[str], Optional[str]], None]


@dataclass(slots=True)
class SyncCallbacks:
    on_step_change: Optional[StepChangeCallback] = None
    on_progress: Optional[ProgressCallback] = None
    on_log: Optional[LogCallback] = None


@dataclass(slots=True)
class SyncErrorInfo:
    type: str
    message: str
    recoverable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "recoverable": self.recoverable,
        }


@dataclass(slots=True)
class SyncResult:
    task_id: str
    status: SyncTaskStatus
    started_at: str
    finished_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    current_step: int = 0
    total_steps: int = TOTAL_SYNC_STEPS
    failed_step: Optional[int] = None
    summary: dict[str, Any] = field(default_factory=dict)
    error: Optional[SyncErrorInfo] = None

    @property
    def success(self) -> bool:
        return self.status == SyncTaskStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "failed_step": self.failed_step,
            "summary": self.summary,
            "error": self.error.to_dict() if self.error else None,
        }


def get_sync_step(number: int) -> SyncStep:
    return SYNC_STEP_MAP[number]


def format_timestamp(value: Optional[datetime] = None) -> str:
    return (value or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def build_task_id(value: Optional[datetime] = None) -> str:
    current = value or datetime.now()
    return current.strftime("sync_%Y%m%d_%H%M%S")
