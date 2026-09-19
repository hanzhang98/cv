from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backtest import BacktestConfig, run_backtest, summarize
from .data import load_bars
from .moomoo_data import download_history
from .strategies import asia_shock_setups, us_open_rejection_setups


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nq-reversion")
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help="download an exact NQ contract")
    download.add_argument("--symbol", required=True, help="for example US.NQ2612")
    download.add_argument("--start", required=True, help="YYYY-MM-DD")
    download.add_argument("--end", required=True, help="YYYY-MM-DD")
    download.add_argument("--output", required=True)
    download.add_argument("--host", default="127.0.0.1")
    download.add_argument("--port", default=11111, type=int)

    test = commands.add_parser("backtest", help="backtest one-minute OHLCV CSV data")
    test.add_argument("--csv", required=True)
    test.add_argument(
        "--source-timezone",
        required=True,
        help="timezone of naive CSV timestamps, normally America/Chicago for CME",
    )
    test.add_argument(
        "--strategy",
        choices=("asia", "us-open", "all"),
        default="all",
    )
    test.add_argument("--output-dir", default="results")
    test.add_argument("--point-value", type=float, default=20.0)
    test.add_argument("--tick-size", type=float, default=0.25)
    test.add_argument("--slippage-ticks", type=float, default=1.0)
    test.add_argument("--commission-per-side", type=float, default=2.50)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.command == "download":
        frame = download_history(
            symbol=arguments.symbol,
            start=arguments.start,
            end=arguments.end,
            output=arguments.output,
            host=arguments.host,
            port=arguments.port,
        )
        print(f"wrote {len(frame):,} bars to {arguments.output}")
        return

    bars = load_bars(arguments.csv, arguments.source_timezone)
    setups = []
    if arguments.strategy in ("asia", "all"):
        setups.extend(asia_shock_setups(bars))
    if arguments.strategy in ("us-open", "all"):
        setups.extend(us_open_rejection_setups(bars))
    execution = BacktestConfig(
        point_value=arguments.point_value,
        tick_size=arguments.tick_size,
        slippage_ticks_per_market_fill=arguments.slippage_ticks,
        commission_per_side=arguments.commission_per_side,
    )
    trades = run_backtest(bars, setups, execution)
    report = summarize(trades, execution)
    report["bars"] = len(bars)
    report["start"] = bars.index.min().isoformat()
    report["end"] = bars.index.max().isoformat()
    report["setups"] = len(setups)

    output = Path(arguments.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trades.to_csv(output / "trades.csv", index=False)
    (output / "summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
