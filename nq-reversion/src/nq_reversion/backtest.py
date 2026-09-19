from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .strategies import TradeSetup


@dataclass(frozen=True)
class BacktestConfig:
    point_value: float = 20.0
    tick_size: float = 0.25
    slippage_ticks_per_market_fill: float = 1.0
    commission_per_side: float = 2.50


TRADE_COLUMNS = [
    "strategy",
    "signal_time",
    "entry_time",
    "exit_time",
    "side",
    "entry_price",
    "exit_price",
    "target_price",
    "stop_price",
    "exit_reason",
    "bars_held",
    "signal_strength",
    "gross_points",
    "net_pnl",
]


def run_backtest(
    bars: pd.DataFrame,
    setups: list[TradeSetup],
    config: BacktestConfig = BacktestConfig(),
) -> pd.DataFrame:
    """Execute setups at next-bar open with one position at a time.

    If stop and target are both touched in one OHLC bar, the stop is assumed
    first. This intentionally pessimistic rule avoids inventing intrabar path.
    """
    if not bars.index.is_monotonic_increasing:
        raise ValueError("bars must be sorted")
    slippage = config.tick_size * config.slippage_ticks_per_market_fill
    records: list[dict[str, object]] = []
    occupied_through = -1

    for setup in sorted(setups, key=lambda item: item.signal_time):
        signal_position = bars.index.searchsorted(setup.signal_time)
        if (
            signal_position >= len(bars)
            or bars.index[signal_position] != setup.signal_time
            or signal_position + 1 >= len(bars)
        ):
            continue
        entry_position = signal_position + 1
        if entry_position <= occupied_through:
            continue

        entry = float(bars["open"].iloc[entry_position]) + setup.side * slippage
        stop = entry - setup.side * setup.stop_distance
        target = setup.target_price
        if setup.side * (target - entry) <= 0:
            continue

        final_position = min(
            entry_position + setup.max_hold_bars - 1,
            len(bars) - 1,
        )
        exit_price = np.nan
        exit_reason = "timeout"
        exit_position = final_position
        for position in range(entry_position, final_position + 1):
            bar = bars.iloc[position]
            if setup.side > 0:
                stop_hit = float(bar["low"]) <= stop
                target_hit = float(bar["high"]) >= target
                gap_stop = float(bar["open"]) <= stop
            else:
                stop_hit = float(bar["high"]) >= stop
                target_hit = float(bar["low"]) <= target
                gap_stop = float(bar["open"]) >= stop

            if stop_hit:
                raw_stop_fill = float(bar["open"]) if gap_stop else stop
                exit_price = raw_stop_fill - setup.side * slippage
                exit_reason = "stop"
                exit_position = position
                break
            if target_hit:
                exit_price = target
                exit_reason = "target"
                exit_position = position
                break

        if np.isnan(exit_price):
            exit_price = (
                float(bars["close"].iloc[exit_position]) - setup.side * slippage
            )

        gross_points = setup.side * (exit_price - entry)
        net_pnl = (
            gross_points * config.point_value - 2 * config.commission_per_side
        )
        records.append(
            {
                "strategy": setup.strategy,
                "signal_time": setup.signal_time,
                "entry_time": bars.index[entry_position],
                "exit_time": bars.index[exit_position],
                "side": setup.side,
                "entry_price": entry,
                "exit_price": exit_price,
                "target_price": target,
                "stop_price": stop,
                "exit_reason": exit_reason,
                "bars_held": exit_position - entry_position + 1,
                "signal_strength": setup.signal_strength,
                "gross_points": gross_points,
                "net_pnl": net_pnl,
            }
        )
        occupied_through = exit_position
    return pd.DataFrame.from_records(records, columns=TRADE_COLUMNS)


def summarize(trades: pd.DataFrame, config: BacktestConfig) -> dict[str, object]:
    if trades.empty:
        return {
            "assumptions": asdict(config),
            "trades": 0,
            "net_pnl": 0.0,
            "expectancy": None,
            "win_rate": None,
            "profit_factor": None,
            "max_drawdown": 0.0,
        }
    pnl = trades["net_pnl"]
    wins = float(pnl[pnl > 0].sum())
    losses = float(-pnl[pnl < 0].sum())
    equity = pnl.cumsum()
    drawdown = equity - equity.cummax().clip(lower=0)
    return {
        "assumptions": asdict(config),
        "trades": int(len(trades)),
        "net_pnl": round(float(pnl.sum()), 2),
        "expectancy": round(float(pnl.mean()), 2),
        "win_rate": round(float((pnl > 0).mean()), 4),
        "profit_factor": round(wins / losses, 3) if losses else None,
        "max_drawdown": round(float(drawdown.min()), 2),
    }
