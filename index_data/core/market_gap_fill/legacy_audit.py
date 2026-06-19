from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from config import settings
from config.constants import AssetType
from core.market_gap_fill.catalog import get_tickflow_catalog_evidence
from core.market_gap_fill.models import GapFillConfirmationCode
from dao.market_gap_fill_audit_dao import market_gap_fill_audit_dao
from dao.market_gap_fill_dao import market_gap_fill_dao
from dao.meta_dao import meta_dao
from dao.tickflow_gap_fill_runtime_dao import tickflow_gap_fill_runtime_dao
from data_provider.tdx_vipdoc_provider import TdxVipdocProvider
from data_provider.tickflow_adapter import TickFlowAdapter
from data_provider.tickflow_adapter import TickFlowCallConfig
from data_provider.tickflow_adapter import TickFlowGapFillError
from utils.validators import ValidationError


REPORT_SCHEMA_VERSION = 1
BASELINE_TASK_COUNT = 4197


class LegacyGapFillAuditService:
    def __init__(
        self,
        tdx_provider: TdxVipdocProvider | None = None,
        tickflow_adapter: TickFlowAdapter | None = None,
        wall_clock: Callable[[], datetime] = datetime.now,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.tdx_provider = tdx_provider or TdxVipdocProvider()
        self.tickflow_adapter = tickflow_adapter or TickFlowAdapter(
            call_config=TickFlowCallConfig(
                timeout_seconds=settings.TICKFLOW_GAP_FILL_TIMEOUT_SECONDS,
                max_retries=0,
                adjust="none",
                count_limit=settings.TICKFLOW_KLINE_COUNT_LIMIT,
            )
        )
        self.wall_clock = wall_clock
        self.clock = clock
        self.sleeper = sleeper

    def audit(self, output_path: str | Path) -> dict:
        (
            tasks,
            start_scope,
        ) = market_gap_fill_audit_dao.snapshot_tasks_and_fingerprint()
        start_catalog_hash = (
            market_gap_fill_audit_dao.compute_tickflow_catalog_hash()
        )
        audit_id = "gap_audit_" + uuid.uuid4().hex
        run_id = "gap_audit_runtime_" + uuid.uuid4().hex
        results = []
        tickflow_requests = 0
        with self.tdx_provider.package_lock():
            start_manifest = self.tdx_provider.read_manifest()
            assets = {
                asset["asset_code"]: asset
                for asset in meta_dao.get_active_assets()
            }
            tasks_by_asset: dict[str, list[dict]] = {}
            for task in tasks:
                tasks_by_asset.setdefault(task["asset_code"], []).append(task)
            lease_acquired = tickflow_gap_fill_runtime_dao.claim_discovery_lease(
                run_id=run_id,
                now_text=self._now_text(microseconds=True),
                ttl_seconds=(
                    settings.TICKFLOW_GAP_FILL_MAX_SECONDS
                    + settings.TICKFLOW_GAP_FILL_TIMEOUT_SECONDS
                    + 60
                ),
            )
            started = self.clock()
            try:
                for asset_code, asset_tasks in tasks_by_asset.items():
                    asset = assets.get(asset_code) or {
                        "asset_code": asset_code,
                        "asset_type": asset_tasks[0].get("asset_type"),
                        "exchange": asset_tasks[0].get("exchange"),
                    }
                    tdx = self.tdx_provider.read_asset_history(
                        exchange=asset.get("exchange"),
                        asset_code=asset_code,
                        asset_type=asset.get("asset_type") or "",
                        target_date=max(
                            task["missing_date"] for task in asset_tasks
                        ),
                    )
                    catalog = get_tickflow_catalog_evidence(
                        asset_code=asset_code,
                        asset_type=asset.get("asset_type") or "",
                        wall_clock=self.wall_clock,
                    )
                    tickflow = {
                        "status": "not_requested",
                        "valid": {},
                        "invalid_dates": set(),
                    }
                    should_request = (
                        lease_acquired
                        and catalog["qualified"]
                        and catalog["status"] == "ACTIVE"
                        and tickflow_requests
                        < settings.TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN
                        and self.clock() - started
                        < settings.TICKFLOW_GAP_FILL_MAX_SECONDS
                    )
                    if should_request:
                        reservation = self._reserve_request(started)
                        if reservation:
                            tickflow_requests += 1
                            tickflow = self._fetch_tickflow(
                                asset_code=asset_code,
                                exchange=catalog["exchange"],
                                end_date=max(
                                    task["missing_date"]
                                    for task in asset_tasks
                                ),
                            )
                    market_dates = market_gap_fill_dao.get_market_dates(
                        asset_code
                    )
                    for task in asset_tasks:
                        results.append(
                            _classify_audit_task(
                                task=task,
                                market_dates=market_dates,
                                tdx=tdx,
                                catalog=catalog,
                                tickflow=tickflow,
                            )
                        )
            finally:
                if lease_acquired:
                    tickflow_gap_fill_runtime_dao.release_discovery_lease(
                        run_id
                    )
            end_manifest = self.tdx_provider.read_manifest()

        end_scope = market_gap_fill_audit_dao.compute_scope_fingerprint()
        end_catalog_hash = (
            market_gap_fill_audit_dao.compute_tickflow_catalog_hash()
        )
        report = {
            "audit_id": audit_id,
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": self._now_text(),
            "actual_task_count": len(tasks),
            "baseline_task_count": BASELINE_TASK_COUNT,
            "baseline_task_count_delta": len(tasks) - BASELINE_TASK_COUNT,
            "scope_fingerprint": start_scope,
            "tdx_package_id": start_manifest["package_id"],
            "tickflow_catalog_hash": start_catalog_hash,
            "tickflow_requests": tickflow_requests,
            "tasks": results,
            "summary": _summarize(results),
            "applicable": (
                start_scope == end_scope
                and start_catalog_hash == end_catalog_hash
                and start_manifest["package_id"]
                == end_manifest["package_id"]
            ),
        }
        report["report_hash"] = compute_report_hash(report)
        Path(output_path).write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return report

    def apply(self, input_path: str | Path, apply: bool = False) -> dict:
        report = json.loads(Path(input_path).read_text(encoding="utf-8"))
        if report.get("report_schema_version") != REPORT_SCHEMA_VERSION:
            raise ValidationError("LEGACY_AUDIT_SCHEMA_UNSUPPORTED")
        if compute_report_hash(report) != report.get("report_hash"):
            raise ValidationError("LEGACY_AUDIT_REPORT_HASH_INVALID")
        if not report.get("applicable"):
            raise ValidationError("LEGACY_AUDIT_NOT_APPLICABLE")
        if market_gap_fill_audit_dao.is_applied(
            report["audit_id"], report["report_hash"]
        ):
            return {
                "status": "already_applied",
                "audit_id": report["audit_id"],
            }
        if not apply:
            return {
                "status": "preview",
                "audit_id": report["audit_id"],
                "summary": report["summary"],
            }
        if (
            market_gap_fill_audit_dao.compute_tickflow_catalog_hash()
            != report["tickflow_catalog_hash"]
        ):
            raise ValidationError("LEGACY_AUDIT_CATALOG_CHANGED")
        with self.tdx_provider.package_lock():
            if (
                self.tdx_provider.read_manifest()["package_id"]
                != report["tdx_package_id"]
            ):
                raise ValidationError("LEGACY_AUDIT_TDX_PACKAGE_CHANGED")
            return market_gap_fill_audit_dao.apply_report(report)

    def _fetch_tickflow(
        self,
        asset_code: str,
        exchange: str,
        end_date: str,
    ) -> dict:
        try:
            response = self.tickflow_adapter.fetch_daily_range(
                asset_code=asset_code,
                exchange=exchange,
                start_date=settings.DATA_COLLECTION_DEFAULT_START_DATE,
                end_date=end_date,
            )
        except TickFlowGapFillError as exc:
            tickflow_gap_fill_runtime_dao.record_error(
                exc.category,
                self._now_text(microseconds=True),
                "legacy-audit-v1",
            )
            return {
                "status": "error",
                "error_code": exc.category,
                "valid": {},
                "invalid_dates": set(),
            }
        tickflow_gap_fill_runtime_dao.record_success()
        return {
            "status": "completed",
            "valid": {
                date: value["bar"]
                for date, value in response.items()
                if value.get("status") == "hit"
            },
            "invalid_dates": {
                date
                for date, value in response.items()
                if value.get("status") == "invalid"
            },
        }

    def _reserve_request(self, started: float) -> bool:
        while self.clock() - started < settings.TICKFLOW_GAP_FILL_MAX_SECONDS:
            reservation = tickflow_gap_fill_runtime_dao.reserve_request_start(
                now_text=self._now_text(microseconds=True),
                interval_seconds=settings.TICKFLOW_GAP_FILL_SLEEP_SECONDS,
                config_signature="legacy-audit-v1",
            )
            if reservation.get("breaker_open"):
                return False
            if reservation.get("reserved"):
                return True
            wait_seconds = float(reservation.get("wait_seconds") or 0)
            if (
                self.clock() - started + wait_seconds
                >= settings.TICKFLOW_GAP_FILL_MAX_SECONDS
            ):
                return False
            self.sleeper(wait_seconds)
        return False

    def _now_text(self, microseconds: bool = False) -> str:
        timespec = "microseconds" if microseconds else "seconds"
        return self.wall_clock().isoformat(sep=" ", timespec=timespec)


def _classify_audit_task(
    task: dict,
    market_dates: set[str],
    tdx: dict,
    catalog: dict,
    tickflow: dict,
) -> dict:
    trade_date = task["missing_date"]
    base = {
        "task_id": task["task_id"],
        "asset_code": task["asset_code"],
        "missing_date": trade_date,
    }
    if task.get("status") == "CONFIRMED":
        result = task.get("last_error_code")
        if not result or not str(result).startswith("CONFIRMED_"):
            result = GapFillConfirmationCode.NO_SOURCE_BAR
        return {
            **base,
            "result": result,
            "source_results": _task_source_results(task),
        }
    if trade_date in market_dates:
        return {**base, "result": "KEEP_FILLED", "source_results": {}}
    tdx_valid = tdx.get("valid") or {}
    if trade_date in tdx_valid:
        return {
            **base,
            "result": "FILL_FROM_TDX",
            "market_row": tdx_valid[trade_date],
            "source_results": {
                "tdx": {"status": "valid"},
                "tickflow": {"status": tickflow["status"]},
            },
        }
    tickflow_valid = tickflow.get("valid") or {}
    if trade_date in tickflow_valid:
        return {
            **base,
            "result": "FILL_FROM_TICKFLOW",
            "market_row": tickflow_valid[trade_date],
            "source_results": {
                "tdx": {"status": _tdx_status(tdx, trade_date)},
                "tickflow": {"status": "valid"},
            },
        }
    if (
        tdx.get("file_status") == "invalid"
        or trade_date in set(tdx.get("invalid_dates") or [])
        or trade_date in set(tickflow.get("invalid_dates") or [])
    ):
        return {
            **base,
            "result": "FAILED_SOURCE_VALIDATION",
            "source_results": {
                "tdx": {"status": _tdx_status(tdx, trade_date)},
                "tickflow": {"status": tickflow["status"]},
            },
        }
    tickflow_applicable = task.get("asset_type") != AssetType.LOF
    if tickflow_applicable and (
        not catalog["qualified"] or catalog["status"] == "CONFLICT"
    ):
        return {
            **base,
            "result": "PENDING_SOURCE_CATALOG",
            "source_results": {
                "tdx": {"status": _tdx_status(tdx, trade_date)},
                "tickflow": {
                    "status": (
                        "TICKFLOW_CATALOG_CONFLICT"
                        if catalog["status"] == "CONFLICT"
                        else catalog["reason"]
                    )
                },
            },
        }
    if (
        tickflow_applicable
        and catalog["status"] == "ACTIVE"
        and tickflow["status"] != "completed"
    ):
        return {
            **base,
            "result": "PENDING_TICKFLOW_DISCOVERY",
            "source_results": {
                "tdx": {"status": _tdx_status(tdx, trade_date)},
                "tickflow": {"status": tickflow["status"]},
            },
        }
    if trade_date in set(tdx.get("zero_dates") or []):
        result = GapFillConfirmationCode.ZERO_VOLUME_PLACEHOLDER
    else:
        first_dates = []
        if market_dates:
            first_dates.append(min(market_dates))
        if tdx.get("first_valid_date"):
            first_dates.append(tdx["first_valid_date"])
        if tickflow_valid:
            first_dates.append(min(tickflow_valid))
        result = (
            GapFillConfirmationCode.OUTSIDE_SOURCE_COVERAGE
            if not first_dates or trade_date < min(first_dates)
            else GapFillConfirmationCode.NO_SOURCE_BAR
        )
    return {
        **base,
        "result": result,
        "source_results": {
            "tdx": {"status": _tdx_status(tdx, trade_date)},
            "tickflow": {"status": tickflow["status"]},
        },
    }


def _tdx_status(tdx: dict, trade_date: str) -> str:
    if tdx.get("file_status") != "ready":
        return tdx.get("file_status") or "missing"
    if trade_date in set(tdx.get("zero_dates") or []):
        return "zero"
    if trade_date in set(tdx.get("invalid_dates") or []):
        return "invalid"
    return "absent"


def _task_source_results(task: dict) -> dict:
    try:
        detail = json.loads(task.get("detail_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(detail, dict):
        return {}
    source_results = detail.get("source_results")
    return source_results if isinstance(source_results, dict) else {}


def _summarize(results: list[dict]) -> dict:
    summary: dict[str, int] = {}
    for item in results:
        result = item["result"]
        summary[result] = summary.get(result, 0) + 1
    return dict(sorted(summary.items()))


def compute_report_hash(report: dict) -> str:
    payload = copy.deepcopy(report)
    payload.pop("report_hash", None)
    normalized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


legacy_gap_fill_audit_service = LegacyGapFillAuditService()
