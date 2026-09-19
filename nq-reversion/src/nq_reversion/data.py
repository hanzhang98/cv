from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BAR_COLUMNS = ("open", "high", "low", "close", "volume")
TIME_COLUMNS = ("time", "time_key", "datetime", "timestamp")


def normalize_bars(frame: pd.DataFrame, source_timezone: str) -> pd.DataFrame:
    """Return sorted, UTC-indexed OHLCV bars.

    Moomoo returns naive exchange-local ``time_key`` values. The source
    timezone is deliberately explicit because silently treating those values
    as UTC invalidates session tests, especially around daylight-saving time.
    """
    bars = frame.copy()
    bars.columns = [str(column).strip().lower() for column in bars.columns]
    time_column = next((name for name in TIME_COLUMNS if name in bars.columns), None)
    if time_column is None:
        if isinstance(bars.index, pd.DatetimeIndex):
            timestamps = bars.index
        else:
            raise ValueError(f"missing timestamp column; expected one of {TIME_COLUMNS}")
    else:
        timestamps = pd.DatetimeIndex(pd.to_datetime(bars.pop(time_column), errors="raise"))

    missing = set(BAR_COLUMNS) - set(bars.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {sorted(missing)}")

    if timestamps.tz is None:
        timestamps = timestamps.tz_localize(
            ZoneInfo(source_timezone), ambiguous="infer", nonexistent="shift_forward"
        )
    timestamps = timestamps.tz_convert("UTC")
    bars.index = timestamps
    bars.index.name = "time"

    for column in BAR_COLUMNS:
        bars[column] = pd.to_numeric(bars[column], errors="raise")
    bars = bars.loc[:, list(BAR_COLUMNS)].sort_index()
    bars = bars[~bars.index.duplicated(keep="last")]
    if bars.empty:
        raise ValueError("no bars found")
    if (bars["high"] < bars[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("high is below another OHLC value")
    if (bars["low"] > bars[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("low is above another OHLC value")
    if (bars["volume"] < 0).any():
        raise ValueError("volume cannot be negative")
    return bars


def load_bars(path: str | Path, source_timezone: str) -> pd.DataFrame:
    return normalize_bars(pd.read_csv(path), source_timezone)
