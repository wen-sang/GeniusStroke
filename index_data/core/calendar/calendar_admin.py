from __future__ import annotations

import argparse
import json

from core.calendar.calendar_service import CalendarCoverageError
from core.calendar.calendar_service import calendar_service


EXIT_SUCCESS = 0
EXIT_BUSINESS_FAILURE = 1
EXIT_RUNTIME_FAILURE = 2


def main(argv: list[str] | None = None, service=calendar_service) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = _run_command(args, service)
    except CalendarCoverageError as error:
        _print_json({"status": "failed", "error": str(error)})
        return EXIT_BUSINESS_FAILURE
    except ValueError as error:
        _print_json({"status": "failed", "error": str(error)})
        return EXIT_BUSINESS_FAILURE
    except Exception as error:
        _print_json({"status": "error", "error": str(error)})
        return EXIT_RUNTIME_FAILURE

    _print_json(result)
    if result.get("hard_failure"):
        return EXIT_BUSINESS_FAILURE
    return EXIT_SUCCESS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calendar_admin",
        description="Manage exchange and legacy trading calendars.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show calendar coverage status")
    subparsers.add_parser(
        "refresh-exchange-calendar",
        help="Refresh trade_calendar_exchange only",
    )
    subparsers.add_parser(
        "sync-legacy-calendar",
        help="Sync old trade_calendar from SH open-date projection",
    )
    annual_parser = subparsers.add_parser(
        "annual-refresh",
        help="Refresh exchange calendars and sync legacy calendar",
    )
    annual_parser.add_argument("--required-end", required=True)
    return parser


def _run_command(args, service) -> dict:
    if args.command == "status":
        return service.calendar_status()
    if args.command == "refresh-exchange-calendar":
        return {
            "status": "ok",
            "summary": service.refresh_exchange_calendar(),
        }
    if args.command == "sync-legacy-calendar":
        return {
            "status": "ok",
            "summary": service.sync_legacy_trade_calendar(),
        }
    if args.command == "annual-refresh":
        return {
            "status": "ok",
            "summary": service.annual_refresh(args.required_end),
        }
    raise ValueError(f"unsupported command: {args.command}")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
