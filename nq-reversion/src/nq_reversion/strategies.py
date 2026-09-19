from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TradeSetup:
    signal_time: pd.Timestamp
    side: int
    target_price: float
    stop_distance: float
    max_hold_bars: int
    strategy: str
    signal_strength: float


@dataclass(frozen=True)
class AsiaShockConfig:
    session_start: time = time(19, 0)
    session_end: time = time(2, 55)
    shock_z: float = 3.0
    minimum_shock_points: float = 8.0
    minimum_vwap_distance: float = 6.0
    volatility_lookback: int = 240
    vwap_lookback: int = 60
    atr_lookback: int = 30
    stop_atr: float = 1.25
    minimum_stop_points: float = 10.0
    max_hold_bars: int = 12
    cooldown_bars: int = 12


@dataclass(frozen=True)
class USOpenConfig:
    minimum_overnight_move: float = 35.0
    minimum_rejection: float = 8.0
    rejection_fraction: float = 0.35
    stop_atr: float = 1.25
    minimum_stop_points: float = 15.0
    atr_lookback: int = 30
    max_hold_bars: int = 25


def _market_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("bars must have a timezone-aware DatetimeIndex")
    local = bars.copy()
    local.index = local.index.tz_convert(ZoneInfo("America/New_York"))
    return local


def _in_wrapped_session(index: pd.DatetimeIndex, start: time, end: time) -> np.ndarray:
    values = np.array(index.time)
    if start <= end:
        return (values >= start) & (values <= end)
    return (values >= start) | (values <= end)


def _true_range(bars: pd.DataFrame) -> pd.Series:
    prior_close = bars["close"].shift(1)
    return pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - prior_close).abs(),
            (bars["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _rolling_vwap(bars: pd.DataFrame, lookback: int) -> pd.Series:
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    volume = bars["volume"].replace(0, np.nan)
    numerator = (typical * volume).rolling(lookback, min_periods=lookback // 2).sum()
    denominator = volume.rolling(lookback, min_periods=lookback // 2).sum()
    return numerator / denominator


def asia_shock_setups(
    bars: pd.DataFrame, config: AsiaShockConfig = AsiaShockConfig()
) -> list[TradeSetup]:
    """Fade isolated Asian-session shocks toward trailing VWAP.

    Every feature is available at the signal bar close. Entry is delegated to
    the next bar by the execution simulator, preventing same-bar lookahead.
    """
    local = _market_bars(bars)
    change = local["close"].diff()
    sigma = change.rolling(
        config.volatility_lookback,
        min_periods=max(30, config.volatility_lookback // 2),
    ).std().shift(1)
    zscore = change / sigma
    vwap = _rolling_vwap(local, config.vwap_lookback)
    atr = _true_range(local).rolling(
        config.atr_lookback, min_periods=config.atr_lookback
    ).mean()

    eligible = (
        _in_wrapped_session(local.index, config.session_start, config.session_end)
        & (change.abs() >= config.minimum_shock_points)
        & (zscore.abs() >= config.shock_z)
        & ((local["close"] - vwap).abs() >= config.minimum_vwap_distance)
    )

    setups: list[TradeSetup] = []
    last_position = -config.cooldown_bars - 1
    for position in np.flatnonzero(eligible):
        if position - last_position <= config.cooldown_bars:
            continue
        side = -1 if change.iloc[position] > 0 else 1
        target = float(vwap.iloc[position])
        close = float(local["close"].iloc[position])
        if side * (target - close) <= 0:
            continue
        setups.append(
            TradeSetup(
                signal_time=local.index[position].tz_convert("UTC"),
                side=side,
                target_price=target,
                stop_distance=max(
                    config.minimum_stop_points, float(atr.iloc[position]) * config.stop_atr
                ),
                max_hold_bars=config.max_hold_bars,
                strategy="asia_shock",
                signal_strength=float(abs(zscore.iloc[position])),
            )
        )
        last_position = position
    return setups


def us_open_rejection_setups(
    bars: pd.DataFrame, config: USOpenConfig = USOpenConfig()
) -> list[TradeSetup]:
    """Fade overnight displacement only after the first five minutes reject it."""
    local = _market_bars(bars)
    atr = _true_range(local).rolling(
        config.atr_lookback, min_periods=config.atr_lookback
    ).mean()
    setups: list[TradeSetup] = []

    # The session key changes at 18:00 ET, matching the CME Globex trade date.
    session_key = (local.index - pd.Timedelta(hours=18)).date
    grouped = local.groupby(session_key, sort=True)
    for _, session in grouped:
        if session.empty:
            continue
        times = np.array(session.index.time)
        overnight = session[(times >= time(18, 0)) | (times < time(9, 30))]
        opening = session[(times >= time(9, 30)) & (times <= time(9, 34))]
        if overnight.empty or len(opening) < 5:
            continue

        prior = local[local.index < overnight.index[0]]
        prior_rth = prior[
            (np.array(prior.index.time) >= time(9, 30))
            & (np.array(prior.index.time) <= time(16, 0))
        ]
        if prior_rth.empty:
            continue
        prior_close = float(prior_rth["close"].iloc[-1])
        pre_open = float(overnight["close"].iloc[-1])
        displacement = pre_open - prior_close
        if abs(displacement) < config.minimum_overnight_move:
            continue

        direction = 1 if displacement > 0 else -1
        extreme = (
            float(opening["high"].max()) if direction > 0 else float(opening["low"].min())
        )
        signal_close = float(opening["close"].iloc[-1])
        rejection = direction * (extreme - signal_close)
        opening_range = float(opening["high"].max() - opening["low"].min())
        required = max(config.minimum_rejection, opening_range * config.rejection_fraction)
        if rejection < required:
            continue

        volume = overnight["volume"].replace(0, np.nan)
        typical = (overnight["high"] + overnight["low"] + overnight["close"]) / 3
        overnight_vwap = float((typical * volume).sum() / volume.sum())
        side = -direction
        if side * (overnight_vwap - signal_close) <= 0:
            continue
        signal_time = opening.index[-1]
        current_atr = float(atr.loc[signal_time])
        if np.isnan(current_atr):
            continue
        setups.append(
            TradeSetup(
                signal_time=signal_time.tz_convert("UTC"),
                side=side,
                target_price=overnight_vwap,
                stop_distance=max(
                    config.minimum_stop_points, current_atr * config.stop_atr
                ),
                max_hold_bars=config.max_hold_bars,
                strategy="us_open_rejection",
                signal_strength=abs(displacement),
            )
        )
    return setups
