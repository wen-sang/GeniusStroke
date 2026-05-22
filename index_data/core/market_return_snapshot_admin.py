import argparse

from core.market_return_snapshot_service import market_return_snapshot_service
from dao.market_dao import market_dao


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild market return snapshots.")
    parser.add_argument(
        "--trade-date",
        help="Trade date to rebuild. Defaults to latest dat_market_daily trade_date.",
    )
    args = parser.parse_args()

    trade_date = args.trade_date or market_dao.get_latest_trade_date_global()
    if not trade_date:
        raise SystemExit("No trade_date found in dat_market_daily.")

    summary = market_return_snapshot_service.rebuild_for_trade_date(trade_date)
    print(summary)


if __name__ == "__main__":
    main()
