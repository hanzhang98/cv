import pandas as pd

from nq_reversion.backtest import BacktestConfig, run_backtest, summarize
from nq_reversion.strategies import TradeSetup


def _bars(rows):
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume"],
        index=pd.date_range("2026-01-05 00:00", periods=len(rows), freq="1min", tz="UTC"),
    )


def test_next_bar_entry_and_target_accounting():
    bars = _bars(
        [
            [100, 101, 99, 100, 10],
            [101, 103, 100, 102, 10],
            [102, 106, 101, 105, 10],
        ]
    )
    setup = TradeSetup(
        signal_time=bars.index[0],
        side=1,
        target_price=105,
        stop_distance=4,
        max_hold_bars=2,
        strategy="test",
        signal_strength=3,
    )
    trades = run_backtest(bars, [setup], BacktestConfig())

    trade = trades.iloc[0]
    assert trade["entry_time"] == bars.index[1]
    assert trade["entry_price"] == 101.25
    assert trade["exit_price"] == 105
    assert trade["exit_reason"] == "target"
    assert trade["net_pnl"] == 70.0


def test_stop_wins_when_stop_and_target_touch_same_bar():
    bars = _bars(
        [
            [100, 100, 100, 100, 10],
            [100, 110, 90, 100, 10],
        ]
    )
    setup = TradeSetup(
        signal_time=bars.index[0],
        side=1,
        target_price=105,
        stop_distance=5,
        max_hold_bars=1,
        strategy="test",
        signal_strength=3,
    )
    trade = run_backtest(bars, [setup]).iloc[0]
    assert trade["exit_reason"] == "stop"
    assert trade["exit_price"] == 95.0


def test_empty_summary_is_json_safe():
    report = summarize(run_backtest(_bars([[100, 100, 100, 100, 1]]), []), BacktestConfig())
    assert report["trades"] == 0
    assert report["expectancy"] is None
