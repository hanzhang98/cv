import numpy as np
import pandas as pd

from nq_reversion.data import normalize_bars
from nq_reversion.strategies import asia_shock_setups


def test_normalize_moomoo_columns_and_timezone():
    raw = pd.DataFrame(
        {
            "time_key": ["2026-01-05 18:00:00", "2026-01-05 18:01:00"],
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [10, 11],
        }
    )
    bars = normalize_bars(raw, "America/Chicago")
    assert str(bars.index.tz) == "UTC"
    assert bars.index[0] == pd.Timestamp("2026-01-06 00:00:00", tz="UTC")


def test_asia_shock_uses_signal_close_then_backtester_can_enter_next_bar():
    index = pd.date_range("2026-01-06 00:00", periods=252, freq="1min", tz="UTC")
    changes = np.tile([-0.25, 0.25], 126)
    closes = 20000 + np.cumsum(changes)
    closes[-2] += 12
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": 100,
        },
        index=index,
    )
    setups = asia_shock_setups(frame)
    assert len(setups) == 1
    assert setups[0].signal_time == index[-2]
    assert setups[0].side == -1
