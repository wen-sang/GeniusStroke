from __future__ import annotations

import argparse
import json
from datetime import datetime

from core.market_gap_fill.models import MarketGapFillRunOptions
from core.market_gap_fill.history_loop import (
    run_history_discovery_until_complete,
)
from core.market_gap_fill.legacy_audit import legacy_gap_fill_audit_service
from core.market_gap_fill.repair_service import market_gap_fill_repair_service
from core.market_gap_fill.service import market_gap_fill_service
from core.market_gap_fill.source_coverage import check_gap_source_coverage
from core.market_gap_fill.tdx_vipdoc_refresh import refresh_tdx_vipdoc
from dao.market_dao import market_dao
from dao.tickflow_gap_fill_runtime_dao import tickflow_gap_fill_runtime_dao
from data_provider.tdx_vipdoc_provider import TdxVipdocProvider


def _validate_date_args(
    target_date: str,
    start_date: str | None,
    end_date: str | None,
) -> None:
    for value in (target_date, start_date, end_date):
        if value:
            datetime.strptime(value, "%Y-%m-%d")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start-date must be <= end-date")
    if end_date and end_date > target_date:
        raise ValueError("end-date must be <= target-date")


def main() -> None:
    parser = argparse.ArgumentParser("market gap fill admin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh-tdx-vipdoc")
    refresh_parser.add_argument("--target-date")

    run_parser = subparsers.add_parser("run-gap-fill")
    run_parser.add_argument("--target-date")
    run_parser.add_argument("--asset-code")
    run_parser.add_argument("--start-date")
    run_parser.add_argument("--end-date")
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview due existing tasks without scanning, claiming, or filling.",
    )
    run_parser.add_argument(
        "--no-external",
        action="store_true",
        help="Skip original route source and TickFlow; only existing rows and TDX are used.",
    )
    run_parser.add_argument(
        "--force-tickflow-retry",
        action="store_true",
    )

    repair_parser = subparsers.add_parser("run-repair")
    repair_parser.add_argument("--asset-code")
    repair_parser.add_argument("--limit", type=int)
    repair_parser.add_argument("--dry-run", action="store_true")

    subparsers.add_parser("show-runtime")

    coverage_parser = subparsers.add_parser("check-gap-source-coverage")
    coverage_parser.add_argument("--target-date")
    coverage_parser.add_argument("--asset-code")
    coverage_parser.add_argument("--start-date")
    coverage_parser.add_argument("--end-date")
    coverage_parser.add_argument("--limit", type=int)

    audit_parser = subparsers.add_parser("audit-legacy-tasks")
    audit_parser.add_argument("--output", required=True)

    apply_parser = subparsers.add_parser("apply-legacy-audit")
    apply_parser.add_argument("--input", required=True)
    apply_parser.add_argument("--apply", action="store_true")

    history_parser = subparsers.add_parser("run-history-discovery")
    history_parser.add_argument("--target-date")
    history_parser.add_argument("--until-complete", action="store_true")

    args = parser.parse_args()
    exit_code = 0
    if args.command == "refresh-tdx-vipdoc":
        result = refresh_tdx_vipdoc(target_date=args.target_date)
    elif args.command == "run-gap-fill":
        if args.force_tickflow_retry and not args.asset_code:
            parser.error("--force-tickflow-retry requires --asset-code")
        target_date = args.target_date or market_dao.get_latest_trade_date_global()
        if not target_date:
            result = {"status": "skipped", "message": "No target_date available"}
        else:
            _validate_date_args(target_date, args.start_date, args.end_date)
            result = market_gap_fill_service.run(
                target_date=target_date,
                options=MarketGapFillRunOptions(
                    asset_code=args.asset_code,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    limit=args.limit,
                    dry_run=args.dry_run,
                    no_external=args.no_external,
                    force_tickflow_retry=args.force_tickflow_retry,
                ),
            )
    elif args.command == "run-repair":
        result = market_gap_fill_repair_service.run(
            sync_id="manual_repair_" + datetime.now().strftime("%Y%m%d%H%M%S"),
            asset_code=args.asset_code,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    elif args.command == "show-runtime":
        provider = TdxVipdocProvider()
        try:
            manifest = provider.read_manifest()
        except Exception as exc:
            manifest = {"status": "NOT_READY", "reason": str(exc)[:200]}
        result = {
            "tdx": manifest,
            "tickflow": tickflow_gap_fill_runtime_dao.get_runtime(),
        }
    elif args.command == "check-gap-source-coverage":
        target_date = args.target_date or market_dao.get_latest_trade_date_global()
        if not target_date:
            result = {"status": "skipped", "message": "No target_date available"}
        else:
            _validate_date_args(target_date, args.start_date, args.end_date)
            result = check_gap_source_coverage(
                target_date=target_date,
                options=MarketGapFillRunOptions(
                    asset_code=args.asset_code,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    limit=args.limit,
                ),
            )
    elif args.command == "audit-legacy-tasks":
        result = legacy_gap_fill_audit_service.audit(args.output)
        if not result["applicable"]:
            exit_code = 1
    elif args.command == "apply-legacy-audit":
        result = legacy_gap_fill_audit_service.apply(
            args.input,
            apply=args.apply,
        )
    elif args.command == "run-history-discovery":
        target_date = args.target_date or market_dao.get_latest_trade_date_global()
        if not target_date:
            result = {"status": "skipped", "message": "No target_date available"}
            exit_code = 1
        else:
            result = run_history_discovery_until_complete(
                service=market_gap_fill_service,
                target_date=target_date,
                until_complete=args.until_complete,
            )
            exit_code = int(result["exit_code"])
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
