from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from config import settings
from config.constants import AssetType, Exchange
from core.market_gap_fill.catalog import get_tickflow_catalog_evidence
from core.market_gap_fill.models import MarketGapFillRunOptions
from dao.data_quality_dao import data_quality_dao
from dao.market_gap_fill_dao import market_gap_fill_dao
from dao.meta_dao import meta_dao
from data_provider.tdx_vipdoc_provider import TdxVipdocProvider
from data_provider.tdx_vipdoc_provider import find_tdx_day_file
from data_provider.tickflow_adapter import TickFlowAdapter
from data_provider.tickflow_adapter import TickFlowCallConfig
from data_provider.tickflow_adapter import TickFlowGapFillError
from dao.tickflow_gap_fill_runtime_dao import tickflow_gap_fill_runtime_dao


ELIGIBLE_ASSET_TYPES = {AssetType.STOCK, AssetType.ETF, AssetType.LOF}


class MarketHistoryDiscoveryService:
    def __init__(
        self,
        tdx_provider: TdxVipdocProvider,
        wall_clock: Callable[[], datetime] = datetime.now,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        tickflow_adapter: TickFlowAdapter | None = None,
    ) -> None:
        self.tdx_provider = tdx_provider
        self.wall_clock = wall_clock
        self.clock = clock
        self.sleeper = sleeper
        self.tickflow_adapter = tickflow_adapter or TickFlowAdapter(
            call_config=TickFlowCallConfig(
                timeout_seconds=settings.TICKFLOW_GAP_FILL_TIMEOUT_SECONDS,
                max_retries=settings.TICKFLOW_GAP_FILL_MAX_RETRIES,
                adjust="none",
                count_limit=settings.TICKFLOW_KLINE_COUNT_LIMIT,
            )
        )

    def run_tdx(
        self,
        target_date: str,
        package_id: str,
        run_id: str,
        options: MarketGapFillRunOptions | None = None,
    ) -> dict:
        options = options or MarketGapFillRunOptions()
        scan_batch_id = (
            "dq_gap_tdx_discovery_"
            + self.wall_clock().strftime("%Y%m%d_%H%M%S_%f")
        )
        detected_at = self._now_text()
        data_quality_dao.create_daily_gap_batch(scan_batch_id, detected_at)
        result = {
            "scan_batch_id": scan_batch_id,
            "processed_assets": 0,
            "filled_tasks": 0,
            "newly_discovered": 0,
            "corrected_assets": 0,
            "conflict_assets": 0,
            "details": [],
            "filled_dates_by_asset": {},
            "_histories": {},
        }
        processed_tasks = 0
        task_limit = options.normalized_limit(
            settings.MARKET_GAP_FILL_MAX_NEW_TASKS_PER_RUN
        )
        try:
            for asset in meta_dao.get_active_assets():
                if not _eligible_asset(asset, options):
                    continue
                if processed_tasks >= task_limit:
                    break
                resolved = self._resolve_exchange(
                    asset=asset,
                    package_id=package_id,
                    run_id=run_id,
                )
                if resolved["conflict"]:
                    result["conflict_assets"] += 1
                    result["details"].append(resolved)
                if resolved["corrected"]:
                    result["corrected_assets"] += 1
                    result["details"].append(resolved)
                    asset = {**asset, "exchange": resolved["exchange"]}

                exchange = resolved["exchange"] or asset.get("exchange")
                history = self.tdx_provider.read_asset_history(
                    exchange=exchange,
                    asset_code=asset["asset_code"],
                    asset_type=asset["asset_type"],
                    target_date=target_date,
                )
                result["_histories"][asset["asset_code"]] = history
                result["processed_assets"] += 1
                existing_tasks = market_gap_fill_dao.list_tasks_for_asset(
                    asset["asset_code"]
                )
                valid = history["valid"]
                zero_dates = set(history["zero_dates"])
                invalid_dates = set(history["invalid_dates"])
                for task in existing_tasks:
                    trade_date = task["missing_date"]
                    if trade_date in valid:
                        source_result = {
                            "status": "valid",
                            "package_id": package_id,
                            "exchange": exchange,
                        }
                    elif trade_date in zero_dates:
                        source_result = {
                            "status": "zero",
                            "package_id": package_id,
                            "exchange": exchange,
                        }
                    elif trade_date in invalid_dates:
                        source_result = {
                            "status": "invalid",
                            "package_id": package_id,
                            "exchange": exchange,
                        }
                    else:
                        source_result = {
                            "status": "absent",
                            "package_id": package_id,
                            "exchange": exchange,
                            "file_status": history["file_status"],
                        }
                    market_gap_fill_dao.merge_source_result(
                        task_id=task["task_id"],
                        source_id="tdx",
                        source_result=source_result,
                    )

                market_dates = market_gap_fill_dao.get_market_dates(
                    asset["asset_code"]
                )
                state = market_gap_fill_dao.get_asset_state(
                    asset["asset_code"]
                )
                existing_task_dates = {
                    task["missing_date"] for task in existing_tasks
                }
                task_hit_dates = {
                    task["missing_date"]
                    for task in existing_tasks
                    if task["missing_date"] in valid
                }
                candidate_dates = set(valid) - market_dates - existing_task_dates
                candidate_dates = {
                    date
                    for date in candidate_dates
                    if _matches_date(date, options)
                }
                cursor_date = (
                    state.get("tdx_discovery_cursor_date")
                    if state.get("tdx_package_id") == package_id
                    else None
                )
                if cursor_date:
                    candidate_dates = {
                        date for date in candidate_dates if date < cursor_date
                    }
                ordered_candidates = sorted(candidate_dates, reverse=True)
                selected_new = ordered_candidates[
                    : settings.MARKET_GAP_FILL_ZERO_HISTORY_DAYS_PER_ASSET
                ]
                selected_dates = sorted(task_hit_dates | set(selected_new))
                if selected_dates:
                    rows = {
                        date: valid[date]
                        for date in selected_dates
                        if date not in market_dates
                    }
                    filled = market_gap_fill_dao.commit_discovered_rows(
                        scan_batch_id=scan_batch_id,
                        detected_at=detected_at,
                        asset_code=asset["asset_code"],
                        exchange=exchange,
                        asset_type=asset["asset_type"],
                        rows_by_date=rows,
                        source_id="tdx",
                        evidence_by_date={
                            date: {
                                "status": "valid",
                                "package_id": package_id,
                                "exchange": exchange,
                            }
                            for date in rows
                        },
                    )
                    result["filled_tasks"] += len(filled)
                    if filled:
                        result["filled_dates_by_asset"][
                            asset["asset_code"]
                        ] = filled
                    result["newly_discovered"] += len(
                        set(filled) & set(selected_new)
                    )
                    processed_tasks += len(filled)

                remaining = ordered_candidates[len(selected_new):]
                completed_at = (
                    self._now_text()
                    if not remaining
                    and history["file_status"] in {"ready", "missing"}
                    else None
                )
                next_cursor = (
                    min(selected_new)
                    if remaining and selected_new
                    else None
                )
                target_start_date = _min_date(
                    min(market_dates) if market_dates else None,
                    history.get("first_valid_date"),
                    state.get("tickflow_first_valid_date"),
                )
                market_gap_fill_dao.upsert_asset_state(
                    asset_code=asset["asset_code"],
                    target_start_date=target_start_date,
                    earliest_generated_date=None,
                    tdx_package_id=package_id,
                    tdx_exchange=exchange,
                    tdx_first_valid_date=history.get("first_valid_date"),
                    tdx_discovery_cursor_date=next_cursor,
                    tdx_discovery_completed_at=completed_at,
                    last_discovery_error_code=history.get(
                        "file_error_code"
                    ),
                    last_discovery_error_message=history.get(
                        "file_error_message"
                    ),
                )
            data_quality_dao.complete_success_batch_without_report(
                scan_batch_id=scan_batch_id,
                issues=[],
                scanned_rows=result["processed_assets"],
                finished_at=self._now_text(),
            )
            return result
        except Exception:
            data_quality_dao.mark_batch_failed(
                scan_batch_id=scan_batch_id,
                scanned_rows=result["processed_assets"],
                error_message="TDX history discovery failed",
                finished_at=self._now_text(),
            )
            raise

    def run_tickflow(
        self,
        target_date: str,
        run_id: str,
        options: MarketGapFillRunOptions | None = None,
    ) -> dict:
        options = options or MarketGapFillRunOptions()
        result = {
            "requested_assets": 0,
            "completed_assets": 0,
            "pending_assets": 0,
            "failed_assets": 0,
            "filled_tasks": 0,
            "filled_dates_by_asset": {},
            "lease_acquired": False,
            "stop_reason": None,
        }
        if options.no_external or not settings.TICKFLOW_GAP_FILL_ENABLED:
            result["stop_reason"] = "TICKFLOW_DISABLED"
            return result

        ttl_seconds = (
            settings.TICKFLOW_GAP_FILL_MAX_SECONDS
            + settings.TICKFLOW_GAP_FILL_TIMEOUT_SECONDS
            + 60
        )
        if not tickflow_gap_fill_runtime_dao.claim_discovery_lease(
            run_id=run_id,
            now_text=self._now_text(microseconds=True),
            ttl_seconds=ttl_seconds,
        ):
            result["stop_reason"] = "TICKFLOW_DISCOVERY_LEASE_BUSY"
            return result
        result["lease_acquired"] = True
        scan_batch_id = (
            "dq_gap_tickflow_discovery_"
            + self.wall_clock().strftime("%Y%m%d_%H%M%S_%f")
        )
        detected_at = self._now_text()
        data_quality_dao.create_daily_gap_batch(scan_batch_id, detected_at)
        started = self.clock()
        processed_tasks = 0
        bounds = market_gap_fill_dao.get_market_date_bounds_by_asset()
        assets = [
            asset
            for asset in meta_dao.get_active_assets()
            if _eligible_asset(asset, options)
        ]
        assets.sort(
            key=lambda asset: (
                (bounds.get(asset["asset_code"]) or {}).get(
                    "first_trade_date"
                )
                or "9999-12-31",
                asset["asset_code"],
            )
        )
        try:
            for asset in assets:
                state = market_gap_fill_dao.get_asset_state(
                    asset["asset_code"]
                )
                catalog = get_tickflow_catalog_evidence(
                    asset_code=asset["asset_code"],
                    asset_type=asset["asset_type"],
                    wall_clock=self.wall_clock,
                )
                if catalog["status"] == "NOT_APPLICABLE":
                    market_gap_fill_dao.upsert_asset_state(
                        asset_code=asset["asset_code"],
                        target_start_date=state.get("target_start_date"),
                        tickflow_catalog_signature=None,
                        tickflow_first_valid_date=None,
                        tickflow_discovery_status="NOT_APPLICABLE",
                        tickflow_discovery_completed_at=self._now_text(),
                        last_discovery_error_code=None,
                        last_discovery_error_message=None,
                    )
                    result["completed_assets"] += 1
                    continue
                if not catalog["qualified"]:
                    self._save_tickflow_state(
                        asset,
                        state,
                        catalog,
                        status="PENDING",
                        error_code=catalog["reason"],
                    )
                    result["pending_assets"] += 1
                    result["stop_reason"] = catalog["reason"]
                    continue
                if catalog["status"] in {"ABSENT", "CONFLICT"}:
                    status = (
                        "FAILED"
                        if catalog["status"] == "CONFLICT"
                        else "COMPLETED"
                    )
                    self._save_tickflow_state(
                        asset,
                        state,
                        catalog,
                        status=status,
                        error_code=(
                            "TICKFLOW_CATALOG_CONFLICT"
                            if status == "FAILED"
                            else None
                        ),
                        clear_first_valid=(
                            catalog["status"] == "ABSENT"
                        ),
                    )
                    if status == "FAILED":
                        result["failed_assets"] += 1
                    else:
                        result["completed_assets"] += 1
                    continue
                if (
                    state.get("tickflow_catalog_signature")
                    == catalog["signature"]
                    and state.get("tickflow_discovery_status") == "COMPLETED"
                ):
                    result["completed_assets"] += 1
                    continue
                if (
                    result["requested_assets"]
                    >= settings.TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN
                ):
                    result["pending_assets"] += 1
                    result["stop_reason"] = "TICKFLOW_BUDGET_EXHAUSTED"
                    continue
                if (
                    self.clock() - started
                    >= settings.TICKFLOW_GAP_FILL_MAX_SECONDS
                ):
                    result["pending_assets"] += 1
                    result["stop_reason"] = "TICKFLOW_DEADLINE"
                    continue
                if not tickflow_gap_fill_runtime_dao.renew_discovery_lease(
                    run_id=run_id,
                    now_text=self._now_text(microseconds=True),
                    ttl_seconds=ttl_seconds,
                ):
                    result["stop_reason"] = "TICKFLOW_DISCOVERY_LEASE_LOST"
                    break
                reservation = self._reserve_tickflow_request(started)
                if not reservation["reserved"]:
                    result["pending_assets"] += 1
                    result["stop_reason"] = reservation["reason"]
                    break

                result["requested_assets"] += 1
                try:
                    response = self.tickflow_adapter.fetch_daily_range(
                        asset_code=asset["asset_code"],
                        exchange=catalog["exchange"],
                        start_date=settings.DATA_COLLECTION_DEFAULT_START_DATE,
                        end_date=target_date,
                    )
                except TickFlowGapFillError as exc:
                    tickflow_gap_fill_runtime_dao.record_error(
                        exc.category,
                        self._now_text(microseconds=True),
                        self._tickflow_config_signature(),
                    )
                    self._save_tickflow_state(
                        asset,
                        state,
                        catalog,
                        status=(
                            "FAILED"
                            if exc.category == "INVALID_RESPONSE"
                            else "PENDING"
                        ),
                        error_code=exc.category,
                        error_message=str(exc),
                    )
                    if exc.category == "INVALID_RESPONSE":
                        result["failed_assets"] += 1
                    else:
                        result["pending_assets"] += 1
                    result["stop_reason"] = exc.category
                    continue

                tickflow_gap_fill_runtime_dao.record_success()
                valid = {
                    date: value["bar"]
                    for date, value in response.items()
                    if value.get("status") == "hit"
                    and date <= target_date
                }
                invalid_dates = {
                    date
                    for date, value in response.items()
                    if value.get("status") == "invalid"
                    and date <= target_date
                }
                existing_tasks = market_gap_fill_dao.list_tasks_for_asset(
                    asset["asset_code"]
                )
                for task in existing_tasks:
                    trade_date = task["missing_date"]
                    market_gap_fill_dao.merge_source_result(
                        task_id=task["task_id"],
                        source_id="tickflow",
                        source_result={
                            "status": (
                                "valid"
                                if trade_date in valid
                                else "invalid"
                                if trade_date in invalid_dates
                                else "absent"
                            ),
                            "catalog_signature": catalog["signature"],
                            "exchange": catalog["exchange"],
                        },
                    )
                market_dates = market_gap_fill_dao.get_market_dates(
                    asset["asset_code"]
                )
                task_dates = {
                    task["missing_date"] for task in existing_tasks
                }
                selected_dates = {
                    date
                    for date in valid
                    if date not in market_dates
                    and (
                        date in task_dates
                        or _matches_date(date, options)
                    )
                }
                rows = {date: valid[date] for date in selected_dates}
                if rows:
                    filled = market_gap_fill_dao.commit_discovered_rows(
                        scan_batch_id=scan_batch_id,
                        detected_at=detected_at,
                        asset_code=asset["asset_code"],
                        exchange=catalog["exchange"],
                        asset_type=asset["asset_type"],
                        rows_by_date=rows,
                        source_id="tickflow",
                        evidence_by_date={
                            date: {
                                "status": "valid",
                                "catalog_signature": catalog["signature"],
                                "exchange": catalog["exchange"],
                            }
                            for date in rows
                        },
                    )
                    result["filled_tasks"] += len(filled)
                    result["filled_dates_by_asset"][
                        asset["asset_code"]
                    ] = filled
                    processed_tasks += len(filled)
                first_valid = min(valid) if valid else None
                target_start_date = _min_date(
                    min(market_dates) if market_dates else None,
                    state.get("tdx_first_valid_date"),
                    first_valid,
                )
                market_gap_fill_dao.upsert_asset_state(
                    asset_code=asset["asset_code"],
                    target_start_date=target_start_date,
                    tickflow_catalog_signature=catalog["signature"],
                    tickflow_first_valid_date=first_valid,
                    tickflow_discovery_status="COMPLETED",
                    tickflow_discovery_completed_at=self._now_text(),
                    last_discovery_error_code=None,
                    last_discovery_error_message=None,
                )
                result["completed_assets"] += 1
                if (
                    processed_tasks
                    >= settings.MARKET_GAP_FILL_MAX_NEW_TASKS_PER_RUN
                ):
                    result["stop_reason"] = "TASK_SOFT_LIMIT"
                    break
            data_quality_dao.complete_success_batch_without_report(
                scan_batch_id=scan_batch_id,
                issues=[],
                scanned_rows=result["requested_assets"],
                finished_at=self._now_text(),
            )
            return result
        except Exception:
            data_quality_dao.mark_batch_failed(
                scan_batch_id=scan_batch_id,
                scanned_rows=result["requested_assets"],
                error_message="TickFlow history discovery failed",
                finished_at=self._now_text(),
            )
            raise
        finally:
            tickflow_gap_fill_runtime_dao.release_discovery_lease(run_id)

    def _save_tickflow_state(
        self,
        asset: dict,
        state: dict,
        catalog: dict,
        status: str,
        error_code: str | None,
        error_message: str | None = None,
        clear_first_valid: bool = False,
    ) -> None:
        market_gap_fill_dao.upsert_asset_state(
            asset_code=asset["asset_code"],
            target_start_date=state.get("target_start_date"),
            tickflow_catalog_signature=catalog.get("signature"),
            tickflow_first_valid_date=(
                None
                if clear_first_valid
                else state.get("tickflow_first_valid_date")
            ),
            tickflow_discovery_status=status,
            tickflow_discovery_completed_at=(
                self._now_text()
                if status in {"COMPLETED", "NOT_APPLICABLE"}
                else None
            ),
            last_discovery_error_code=error_code,
            last_discovery_error_message=(
                error_message[:200] if error_message else None
            ),
        )

    def _reserve_tickflow_request(self, started: float) -> dict:
        while True:
            if (
                self.clock() - started
                >= settings.TICKFLOW_GAP_FILL_MAX_SECONDS
            ):
                return {"reserved": False, "reason": "TICKFLOW_DEADLINE"}
            reservation = tickflow_gap_fill_runtime_dao.reserve_request_start(
                now_text=self._now_text(microseconds=True),
                interval_seconds=settings.TICKFLOW_GAP_FILL_SLEEP_SECONDS,
                config_signature=self._tickflow_config_signature(),
            )
            if reservation.get("breaker_open"):
                return {
                    "reserved": False,
                    "reason": "TICKFLOW_BREAKER_OPEN",
                }
            if reservation.get("reserved"):
                return {"reserved": True, "reason": None}
            wait_seconds = float(reservation.get("wait_seconds") or 0)
            remaining = (
                settings.TICKFLOW_GAP_FILL_MAX_SECONDS
                - (self.clock() - started)
            )
            if wait_seconds > remaining:
                return {"reserved": False, "reason": "TICKFLOW_DEADLINE"}
            self.sleeper(wait_seconds)

    @staticmethod
    def _tickflow_config_signature() -> str:
        return "|".join(
            (
                str(settings.TICKFLOW_GAP_FILL_TIMEOUT_SECONDS),
                str(settings.TICKFLOW_GAP_FILL_MAX_RETRIES),
                "none",
                str(settings.TICKFLOW_KLINE_COUNT_LIMIT),
            )
        )

    def _resolve_exchange(
        self,
        asset: dict,
        package_id: str,
        run_id: str,
    ) -> dict:
        asset_code = asset["asset_code"]
        current_exchange = asset.get("exchange")
        other_exchange = (
            Exchange.SZ if current_exchange == Exchange.SH else Exchange.SH
        )
        current_file = find_tdx_day_file(
            self.tdx_provider.current_dir,
            current_exchange,
            asset_code,
        )
        other_file = find_tdx_day_file(
            self.tdx_provider.current_dir,
            other_exchange,
            asset_code,
        )
        base = {
            "asset_code": asset_code,
            "old_exchange": current_exchange,
            "exchange": current_exchange,
            "corrected": False,
            "conflict": False,
        }
        if current_file and other_file:
            detail = {
                "current_tdx_file": str(current_file),
                "alternate_tdx_file": str(other_file),
            }
            meta_dao.record_asset_reconcile_conflict(
                run_id=run_id,
                asset_code=asset_code,
                field_name="exchange",
                current_value=current_exchange,
                evidence_code="TDX_DUAL_EXCHANGE_FILES",
                tdx_package_id=package_id,
                tickflow_catalog_signature=None,
                detail=detail,
            )
            return {**base, "conflict": True, "detail": detail}
        if current_file or not other_file:
            return base

        catalog = get_tickflow_catalog_evidence(
            asset_code=asset_code,
            asset_type=asset["asset_type"],
            wall_clock=self.wall_clock,
        )
        catalog_exchange = catalog.get("exchange")
        if not catalog.get("qualified"):
            detail = {
                "tdx_exchange": other_exchange,
                "tickflow_status": catalog.get("status"),
                "tickflow_reason": catalog.get("reason"),
            }
            meta_dao.record_asset_reconcile_conflict(
                run_id=run_id,
                asset_code=asset_code,
                field_name="exchange",
                current_value=current_exchange,
                evidence_code="EXCHANGE_CATALOG_UNQUALIFIED",
                tdx_package_id=package_id,
                tickflow_catalog_signature=catalog.get("signature"),
                detail=detail,
            )
            return {**base, "conflict": True, "detail": detail}
        if catalog.get("status") == "CONFLICT" or (
            catalog_exchange and catalog_exchange != other_exchange
        ):
            detail = {
                "tdx_exchange": other_exchange,
                "tickflow_status": catalog.get("status"),
                "tickflow_exchange": catalog_exchange,
            }
            meta_dao.record_asset_reconcile_conflict(
                run_id=run_id,
                asset_code=asset_code,
                field_name="exchange",
                current_value=current_exchange,
                evidence_code="EXCHANGE_SOURCE_CONFLICT",
                tdx_package_id=package_id,
                tickflow_catalog_signature=catalog.get("signature"),
                detail=detail,
            )
            return {**base, "conflict": True, "detail": detail}

        corrected = meta_dao.reconcile_asset_exchange(
            run_id=run_id,
            asset_code=asset_code,
            expected_old_exchange=current_exchange,
            new_exchange=other_exchange,
            evidence_code="TDX_UNIQUE_EXCHANGE_FILE",
            tdx_package_id=package_id,
            tickflow_catalog_signature=catalog.get("signature"),
            detail={
                "tdx_file": str(other_file),
                "tickflow_status": catalog.get("status"),
                "tickflow_exchange": catalog_exchange,
            },
        )
        return {
            **base,
            "exchange": other_exchange if corrected else current_exchange,
            "corrected": corrected,
        }

    def _now_text(self, microseconds: bool = False) -> str:
        timespec = "microseconds" if microseconds else "seconds"
        return self.wall_clock().isoformat(sep=" ", timespec=timespec)


def _eligible_asset(
    asset: dict,
    options: MarketGapFillRunOptions,
) -> bool:
    if asset.get("exchange") not in {Exchange.SH, Exchange.SZ}:
        return False
    if asset.get("asset_type") not in ELIGIBLE_ASSET_TYPES:
        return False
    return not options.asset_code or asset.get("asset_code") == options.asset_code


def _matches_date(
    trade_date: str,
    options: MarketGapFillRunOptions,
) -> bool:
    if options.start_date and trade_date < options.start_date:
        return False
    if options.end_date and trade_date > options.end_date:
        return False
    return True


def _min_date(*values: str | None) -> str | None:
    dates = [value for value in values if value]
    return min(dates) if dates else None
