from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


SOURCE_MULTIPLE = "MULTIPLE"
SOURCE_NO_SOURCE = "NO_SOURCE"
SOURCE_TABLE_MARKET_DAILY = "dat_market_daily"
TRIGGER_MANUAL = "MANUAL"
TRIGGER_DAILY_JOB = "DAILY_JOB"
SCAN_SCOPE_FULL = "FULL"
SCAN_SCOPE_INCREMENTAL = "INCREMENTAL"


class EntityType:
    MARKET_ROW = "MARKET_ROW"
    ASSET = "ASSET"
    EXCHANGE = "EXCHANGE"
    CALENDAR_DATE = "CALENDAR_DATE"


class IssueSeverity:
    ERROR = "ERROR"
    WARN = "WARN"
    CANDIDATE = "CANDIDATE"


class IssueGroup:
    META = "META"
    CALENDAR = "CALENDAR"
    OHLC = "OHLC"
    VOLUME_AMOUNT = "VOLUME_AMOUNT"
    CONTINUITY = "CONTINUITY"


class IssueStatus:
    OPEN = "OPEN"
    IGNORED = "IGNORED"
    CONFIRMED = "CONFIRMED"
    FIXED = "FIXED"


@dataclass(frozen=True)
class DataQualityIssue:
    scan_batch_id: str
    entity_type: str
    entity_id: str
    rule_code: str
    severity: str
    issue_group: str
    field_name: str | None
    actual_value: Any
    expected_value: Any
    detail_json: dict[str, Any]
    detected_at: str
    asset_code: str | None = None
    trade_date: str | None = None
    source_table: str = SOURCE_TABLE_MARKET_DAILY
    source_id: str | None = None
    issue_status: str = IssueStatus.OPEN

    def to_db_tuple(self) -> tuple:
        return (
            self.scan_batch_id,
            self.asset_code,
            self.trade_date,
            self.source_table,
            self.source_id,
            self.entity_type,
            self.entity_id,
            self.rule_code,
            self.severity,
            self.issue_group,
            self.field_name,
            _to_text(self.actual_value),
            _to_text(self.expected_value),
            json.dumps(self.detail_json or {}, ensure_ascii=False, sort_keys=True),
            self.issue_status,
            self.detected_at,
        )

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "scan_batch_id": self.scan_batch_id,
            "asset_code": self.asset_code,
            "trade_date": self.trade_date,
            "source_id": self.source_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "rule_code": self.rule_code,
            "severity": self.severity,
            "issue_group": self.issue_group,
            "field_name": self.field_name,
            "actual_value": _to_text(self.actual_value),
            "expected_value": _to_text(self.expected_value),
            "detail_json": json.dumps(
                self.detail_json or {},
                ensure_ascii=False,
                sort_keys=True,
            ),
            "issue_status": self.issue_status,
            "detected_at": self.detected_at,
        }


@dataclass(frozen=True)
class DataQualityScanResult:
    status: str
    scan_batch_id: str
    source_table: str
    trigger_type: str
    scan_scope: str
    scanned_rows: int
    issue_count: int
    report_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scan_batch_id": self.scan_batch_id,
            "source_table": self.source_table,
            "trigger_type": self.trigger_type,
            "scan_scope": self.scan_scope,
            "scanned_rows": self.scanned_rows,
            "issue_count": self.issue_count,
            "report_path": self.report_path,
        }


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)
