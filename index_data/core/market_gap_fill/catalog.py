from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Callable

from config.constants import AssetType
from dao.asset_catalog_dao import asset_catalog_dao


def get_tickflow_catalog_evidence(
    asset_code: str,
    asset_type: str,
    wall_clock: Callable[[], datetime] = datetime.now,
    max_age_hours: int = 24,
) -> dict:
    if asset_type == AssetType.LOF:
        return {
            "qualified": True,
            "status": "NOT_APPLICABLE",
            "signature": None,
            "matches": [],
            "exchange": None,
            "reason": None,
        }

    sync_log = asset_catalog_dao.get_latest_sync_log("tickflow")
    qualification = qualify_tickflow_catalog(
        sync_log,
        now=wall_clock(),
        max_age_hours=max_age_hours,
    )
    if not qualification["qualified"]:
        return {
            **qualification,
            "status": "PENDING",
            "signature": None,
            "matches": [],
            "exchange": None,
        }

    matches = asset_catalog_dao.get_strict_active_matches(
        source_id="tickflow",
        asset_code=asset_code,
        asset_type=asset_type,
    )
    signature = build_catalog_signature(matches)
    exchanges = sorted(
        {
            str(item.get("exchange") or "")
            for item in matches
            if item.get("exchange")
        }
    )
    if not matches:
        status = "ABSENT"
        exchange = None
    elif len(exchanges) == 1:
        status = "ACTIVE"
        exchange = exchanges[0]
    else:
        status = "CONFLICT"
        exchange = None
    return {
        **qualification,
        "status": status,
        "signature": signature,
        "matches": matches,
        "exchange": exchange,
    }


def qualify_tickflow_catalog(
    sync_log: dict,
    now: datetime,
    max_age_hours: int = 24,
) -> dict:
    if not sync_log or sync_log.get("status") != "success":
        return {
            "qualified": False,
            "reason": "TICKFLOW_CATALOG_NOT_SUCCESS",
            "sync_log": sync_log or {},
        }
    if int(sync_log.get("deactivation_skipped") or 0) != 0:
        return {
            "qualified": False,
            "reason": "TICKFLOW_CATALOG_INCOMPLETE",
            "sync_log": sync_log,
        }
    finished_at = sync_log.get("finished_at")
    try:
        finished = datetime.fromisoformat(str(finished_at))
    except (TypeError, ValueError):
        return {
            "qualified": False,
            "reason": "TICKFLOW_CATALOG_FINISHED_AT_INVALID",
            "sync_log": sync_log,
        }
    if finished < now - timedelta(hours=max_age_hours):
        return {
            "qualified": False,
            "reason": "TICKFLOW_CATALOG_STALE",
            "sync_log": sync_log,
        }
    return {
        "qualified": True,
        "reason": None,
        "sync_log": sync_log,
    }


def build_catalog_signature(matches: list[dict]) -> str:
    normalized = [
        {
            "external_symbol": str(item.get("external_symbol") or ""),
            "asset_type": str(item.get("asset_type") or ""),
            "exchange": str(item.get("exchange") or ""),
            "is_active": int(item.get("is_active") or 0),
        }
        for item in matches
    ]
    normalized.sort(
        key=lambda item: (
            item["external_symbol"],
            item["asset_type"],
            item["exchange"],
            item["is_active"],
        )
    )
    payload = json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()
