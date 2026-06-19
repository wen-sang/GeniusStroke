from __future__ import annotations

import json

from config import settings
from config.constants import AssetType
from core.market_gap_fill.models import GapFillConfirmationCode
from dao.market_gap_fill_dao import market_gap_fill_dao


class MarketGapFillGovernance:
    def classify_claimed_groups(
        self,
        groups: list[dict],
        run_id: str,
        no_external: bool = False,
    ) -> dict:
        result = {
            "filled": 0,
            "confirmed": 0,
            "pending": 0,
            "failed": 0,
            "lease_lost": 0,
        }
        bounds = market_gap_fill_dao.get_market_date_bounds_by_asset()
        tickflow_catalog_version = (
            market_gap_fill_dao.get_tickflow_catalog_version()
        )
        for group in groups:
            asset_state = market_gap_fill_dao.get_asset_state(
                group["asset_code"]
            )
            asset_bounds = bounds.get(group["asset_code"]) or {}
            for original in group["tasks"]:
                task = market_gap_fill_dao.get_task(original["task_id"])
                if not task or task.get("status") == "FILLED":
                    if task and task.get("status") == "FILLED":
                        result["filled"] += 1
                    continue
                if (
                    task.get("status") != "RUNNING"
                    or task.get("run_id") != run_id
                ):
                    result["lease_lost"] += 1
                    continue
                decision = classify_task(
                    task=task,
                    asset_state=asset_state,
                    asset_bounds=asset_bounds,
                    no_external=no_external,
                )
                if decision["status"] == "CONFIRMED":
                    updated = market_gap_fill_dao.mark_confirmed(
                        task_id=task["task_id"],
                        run_id=run_id,
                        confirmation_code=decision["reason"],
                        detail={
                            "final_reason": decision["reason"],
                            "classification": decision["detail"],
                        },
                        last_tdx_package_id=asset_state.get(
                            "tdx_package_id"
                        ),
                        last_tickflow_catalog_version=(
                            tickflow_catalog_version
                            if asset_state.get(
                                "tickflow_discovery_status"
                            ) == "COMPLETED"
                            else None
                        ),
                    )
                    key = "confirmed"
                elif decision["status"] == "FAILED":
                    updated = market_gap_fill_dao.mark_failed_retry(
                        task_id=task["task_id"],
                        run_id=run_id,
                        error_code=decision["reason"],
                        error_message=decision["reason"],
                        retry_delay_minutes=
                            settings.MARKET_GAP_FILL_RETRY_DELAY_MINUTES,
                        detail={
                            "final_reason": decision["reason"],
                            "classification": decision["detail"],
                        },
                    )
                    key = "failed"
                else:
                    updated = market_gap_fill_dao.defer_task(
                        task_id=task["task_id"],
                        run_id=run_id,
                        retry_delay_minutes=
                            settings.MARKET_GAP_FILL_RETRY_DELAY_MINUTES,
                        error_code=decision["reason"],
                        detail={
                            "final_reason": decision["reason"],
                            "classification": decision["detail"],
                        },
                    )
                    key = "pending"
                if updated == 1:
                    result[key] += 1
                else:
                    result["lease_lost"] += 1
        return result


def classify_task(
    task: dict,
    asset_state: dict,
    asset_bounds: dict,
    no_external: bool = False,
) -> dict:
    detail = _parse_detail(task.get("detail_json"))
    source_results = detail.get("source_results")
    if not isinstance(source_results, dict):
        source_results = {}
    tdx = source_results.get("tdx") or {}
    tickflow = source_results.get("tickflow") or {}
    tdx_invalid = (
        tdx.get("status") == "invalid"
        or tdx.get("file_status") == "invalid"
    )
    tickflow_status = asset_state.get("tickflow_discovery_status")
    tickflow_invalid = tickflow.get("status") == "invalid"
    tickflow_applicable = task.get("asset_type") != AssetType.LOF
    tickflow_complete = (
        not tickflow_applicable
        or tickflow_status in {"COMPLETED", "NOT_APPLICABLE"}
    )
    tdx_complete = bool(asset_state.get("tdx_discovery_completed_at"))
    discovery_error_code = asset_state.get(
        "last_discovery_error_code"
    )

    evidence = {
        "tdx_status": tdx.get("status"),
        "tdx_complete": tdx_complete,
        "tickflow_status": tickflow.get("status"),
        "tickflow_discovery_status": tickflow_status,
        "tickflow_complete": tickflow_complete,
        "last_discovery_error_code": discovery_error_code,
    }
    if discovery_error_code == "TICKFLOW_CATALOG_CONFLICT":
        return {
            "status": "PENDING",
            "reason": "PENDING_SOURCE_CATALOG",
            "detail": evidence,
        }
    if tdx_invalid or tickflow_invalid or tickflow_status == "FAILED":
        return {
            "status": "FAILED",
            "reason": "FAILED_SOURCE_VALIDATION",
            "detail": evidence,
        }
    if not tdx_complete:
        return {
            "status": "PENDING",
            "reason": "PENDING_TDX_DISCOVERY",
            "detail": evidence,
        }
    if tickflow_applicable and (no_external or not tickflow_complete):
        return {
            "status": "PENDING",
            "reason": (
                "TICKFLOW_DISABLED_BY_CLI"
                if no_external
                else "PENDING_TICKFLOW_DISCOVERY"
            ),
            "detail": evidence,
        }
    if tdx.get("status") == "zero":
        return {
            "status": "CONFIRMED",
            "reason": GapFillConfirmationCode.ZERO_VOLUME_PLACEHOLDER,
            "detail": evidence,
        }

    first_dates = [
        value
        for value in (
            asset_bounds.get("first_trade_date"),
            asset_state.get("tdx_first_valid_date"),
            asset_state.get("tickflow_first_valid_date"),
        )
        if value
    ]
    missing_date = task["missing_date"]
    if not first_dates or missing_date < min(first_dates):
        return {
            "status": "CONFIRMED",
            "reason": GapFillConfirmationCode.OUTSIDE_SOURCE_COVERAGE,
            "detail": {
                **evidence,
                "first_valid_dates": first_dates,
            },
        }
    return {
        "status": "CONFIRMED",
        "reason": GapFillConfirmationCode.NO_SOURCE_BAR,
        "detail": {
            **evidence,
            "database_first_date": asset_bounds.get("first_trade_date"),
            "database_last_date": asset_bounds.get("last_trade_date"),
        },
    }


def _parse_detail(value: str | None) -> dict:
    try:
        detail = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return detail if isinstance(detail, dict) else {}


market_gap_fill_governance = MarketGapFillGovernance()
