from __future__ import annotations

import argparse
import json

from .config import load_config
from .scanner import run_daily_scan
from .storage import Store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meme-scanner")
    parser.add_argument("--config", default=None, help="TOML configuration path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="record one forward-only daily universe snapshot")

    report = commands.add_parser("report", help="show the latest completed scan")
    report.add_argument("--status", choices=("rejected", "watchlist", "paper_candidate"))
    report.add_argument("--limit", type=int, default=50)

    label = commands.add_parser("label", help="apply a manually reviewed token label")
    label.add_argument("--network", default="solana")
    label.add_argument("--address", required=True)
    label.add_argument(
        "--category",
        required=True,
        choices=("community", "speculative", "meta", "non-meme", "avoid"),
    )
    label.add_argument("--note", default="")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    config = load_config(arguments.config)
    if arguments.command == "scan":
        print(json.dumps(run_daily_scan(config), indent=2))
        return

    store = Store(config.database_path)
    try:
        if arguments.command == "label":
            store.set_label(
                arguments.network,
                arguments.address,
                arguments.category,
                arguments.note,
            )
            print(f"labeled {arguments.network}:{arguments.address} as {arguments.category}")
            return

        rows = store.latest_run_report()
        if arguments.status:
            rows = [row for row in rows if row["status"] == arguments.status]
        output = []
        for row in rows[: arguments.limit]:
            output.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "address": row["address"],
                    "status": row["status"],
                    "score": row["score"],
                    "reasons": json.loads(row["reasons_json"]),
                    "estimated_round_trip_cost_bps": row[
                        "estimated_round_trip_cost_bps"
                    ],
                    "liquidity_usd": row["liquidity_usd"],
                    "volume_24h_usd": row["volume_24h_usd"],
                    "price_usd": row["price_usd"],
                }
            )
        print(json.dumps(output, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
