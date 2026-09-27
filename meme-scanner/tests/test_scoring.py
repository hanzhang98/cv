from datetime import datetime, timedelta, timezone

from meme_scanner.config import EligibilityConfig
from meme_scanner.models import DecisionStatus, PoolSnapshot, TokenRisk
from meme_scanner.scoring import estimated_round_trip_cost_bps, evaluate


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def snapshot() -> PoolSnapshot:
    return PoolSnapshot(
        network="solana",
        pool_address="pool",
        token_address="mint",
        token_symbol="MEME",
        token_name="Meme",
        quote_token_address="sol",
        dex_id="dex",
        observed_at=NOW,
        pool_created_at=NOW - timedelta(days=365),
        price_usd=1.0,
        liquidity_usd=2_000_000,
        volume_24h_usd=1_000_000,
        market_cap_usd=10_000_000,
        fdv_usd=10_000_000,
        price_change_24h_pct=-5,
        buys_24h=100,
        sells_24h=90,
        discovery_sources=("trending_pools",),
    )


def test_cost_model_includes_base_fees_and_pool_impact():
    assert estimated_round_trip_cost_bps(1_000_000, 1_000, 100) == 140


def test_new_observation_stays_watchlist_even_when_market_checks_pass():
    decision = evaluate(
        snapshot(),
        TokenRisk(True, True, 10, 40),
        daily_prices=[1.0],
        label="community",
        config=EligibilityConfig(),
        now=NOW,
    )
    assert decision.status is DecisionStatus.WATCHLIST
    assert "insufficient_forward_history" in decision.reasons


def test_candidate_requires_forward_history_and_range_low():
    prices = [1.0 + index / 100 for index in range(89)] + [1.05]
    decision = evaluate(
        snapshot(),
        TokenRisk(True, True, 10, 40),
        daily_prices=prices,
        label="community",
        config=EligibilityConfig(),
        now=NOW,
    )
    assert decision.status is DecisionStatus.PAPER_CANDIDATE
    assert decision.reasons == ()


def test_active_mint_authority_is_hard_rejection():
    decision = evaluate(
        snapshot(),
        TokenRisk(False, True, 10, 40),
        daily_prices=[1.0],
        label=None,
        config=EligibilityConfig(),
        now=NOW,
    )
    assert decision.status is DecisionStatus.REJECTED
    assert "mint_authority_active" in decision.reasons
