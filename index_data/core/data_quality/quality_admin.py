from __future__ import annotations

import argparse
import json

from core.data_quality.scanner import data_quality_scanner


EXIT_SUCCESS = 0
EXIT_PARAM_ERROR = 1
EXIT_RUNTIME_FAILURE = 2


def main(argv: list[str] | None = None, scanner=data_quality_scanner) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        result = _run_command(args, scanner)
    except ValueError as error:
        _print_json({"status": "failed", "error": str(error)})
        return EXIT_PARAM_ERROR
    except Exception as error:
        _print_json({"status": "error", "error": str(error)})
        return EXIT_RUNTIME_FAILURE

    _print_json(result)
    return EXIT_SUCCESS


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="quality_admin",
        description="Run data quality scans.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser(
        "scan-market-daily",
        help="Run a full dat_market_daily data quality scan",
    )
    scan_parser.add_argument("--report-dir")
    return parser


def _run_command(args, scanner) -> dict:
    if args.command == "scan-market-daily":
        return scanner.scan_market_daily(report_dir=args.report_dir)
    raise ValueError(f"unsupported command: {args.command}")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


if __name__ == "__main__":
    raise SystemExit(main())
