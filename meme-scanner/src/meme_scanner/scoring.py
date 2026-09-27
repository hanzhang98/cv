from __future__ import annotations

from datetime import datetime
import math
from typing import Sequence

from .config import EligibilityConfig
from .models import (
    Decision,
    DecisionStatus,
    HistoryFeatures,
    PoolSnapshot,
    TokenRisk,
)


def estimated_round_trip_cost_bps(
    liquidity_usd: float | None,
    intended_order_usd: float,
    base_cost_bps: float,
) -> float | None:
    if liquidity_usd is None or liquidity_usd <= 0:
        return None
    # A constant-product pool holds roughly half its USD liquidity on each side.
    # Four times order/liquidity approximates entry plus exit impact. The base
    # component covers swap, platform, priority, and unmodeled slippage costs.
    impact_bps = 4 * intended_order_usd / liquidity_usd * 10_000
    return base_cost_bps + impact_bps


def history_features(prices: Sequence[float]) -> HistoryFeatures:
    clean = [float(price) for price in prices if price is not None and price > 0]
    if not clean:
        return HistoryFeatures(0, None, None, None, None)
    high = max(clean)
    low = min(clean)
    range_position = (clean[-1] - low) / (high - low) if high > low else 0.5

    running_high = clean[0]
    maximum_drawdown = 0.0
    for price in clean:
        running_high = max(running_high, price)
        maximum_drawdown = min(maximum_drawdown, price / running_high - 1)

    def trailing_return(period: int) -> float | None:
        if len(clean) <= period:
            return None
        return (clean[-1] / clean[-period - 1] - 1) * 100

    return HistoryFeatures(
        observation_days=len(clean),
        range_position_90d=range_position,
        return_30d_pct=trailing_return(30),
        return_90d_pct=trailing_return(89),
        maximum_drawdown_90d_pct=maximum_drawdown * 100,
    )


def evaluate(
    snapshot: PoolSnapshot,
    risk: TokenRisk,
    daily_prices: Sequence[float],
    label: str | None,
    config: EligibilityConfig,
    now: datetime,
) -> Decision:
    hard_rejections: list[str] = []
    watchlist_reasons: list[str] = []
    history = history_features(daily_prices)

    if snapshot.pool_created_at is None:
        hard_rejections.append("missing_pool_age")
        age_days = 0.0
    else:
        age_days = (now - snapshot.pool_created_at).total_seconds() / 86400
        if age_days < config.minimum_age_days:
            hard_rejections.append("pool_too_new")

    if snapshot.price_usd is None or snapshot.price_usd <= 0:
        hard_rejections.append("missing_price")
    if (
        snapshot.liquidity_usd is None
        or snapshot.liquidity_usd < config.minimum_liquidity_usd
    ):
        hard_rejections.append("insufficient_liquidity")
    if (
        snapshot.volume_24h_usd is None
        or snapshot.volume_24h_usd < config.minimum_volume_24h_usd
    ):
        hard_rejections.append("insufficient_24h_volume")

    cost = estimated_round_trip_cost_bps(
        snapshot.liquidity_usd,
        config.intended_order_usd,
        config.base_round_trip_cost_bps,
    )
    if cost is None or cost > config.maximum_round_trip_cost_bps:
        hard_rejections.append("estimated_cost_too_high")

    if config.require_revoked_authorities:
        if risk.error or risk.mint_authority_revoked is None:
            watchlist_reasons.append("risk_data_unavailable")
        else:
            if not risk.mint_authority_revoked:
                hard_rejections.append("mint_authority_active")
            if not risk.freeze_authority_revoked:
                hard_rejections.append("freeze_authority_active")

    if history.observation_days < config.minimum_forward_history_days:
        watchlist_reasons.append("insufficient_forward_history")
    elif (
        history.range_position_90d is None
        or history.range_position_90d > config.maximum_range_position
    ):
        watchlist_reasons.append("not_near_90d_range_low")

    if config.require_community_label and label != "community":
        watchlist_reasons.append("community_label_required")

    liquidity_score = 0.0
    if snapshot.liquidity_usd and snapshot.liquidity_usd > 0:
        liquidity_score = min(
            30.0,
            15.0 + 10 * math.log10(snapshot.liquidity_usd / config.minimum_liquidity_usd),
        )
    volume_score = 0.0
    if snapshot.volume_24h_usd and snapshot.volume_24h_usd > 0:
        volume_score = min(
            25.0,
            12.5
            + 8 * math.log10(snapshot.volume_24h_usd / config.minimum_volume_24h_usd),
        )
    age_score = min(20.0, max(0.0, age_days / 365 * 20))
    cost_score = 0.0 if cost is None else max(
        0.0, 15 * (1 - cost / config.maximum_round_trip_cost_bps)
    )
    history_score = 0.0
    if history.observation_days >= config.minimum_forward_history_days:
        history_score += 5
        if history.range_position_90d is not None:
            history_score += 5 * (1 - history.range_position_90d)
    score = round(liquidity_score + volume_score + age_score + cost_score + history_score, 3)

    if hard_rejections:
        status = DecisionStatus.REJECTED
        reasons = tuple(sorted(set(hard_rejections + watchlist_reasons)))
    elif watchlist_reasons:
        status = DecisionStatus.WATCHLIST
        reasons = tuple(sorted(set(watchlist_reasons)))
    else:
        status = DecisionStatus.PAPER_CANDIDATE
        reasons = ()
    return Decision(status, score, reasons, cost, history)
