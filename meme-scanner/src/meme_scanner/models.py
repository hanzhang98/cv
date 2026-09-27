from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DecisionStatus(StrEnum):
    REJECTED = "rejected"
    WATCHLIST = "watchlist"
    PAPER_CANDIDATE = "paper_candidate"


@dataclass(frozen=True)
class PoolSnapshot:
    network: str
    pool_address: str
    token_address: str
    token_symbol: str
    token_name: str
    quote_token_address: str
    dex_id: str
    observed_at: datetime
    pool_created_at: datetime | None
    price_usd: float | None
    liquidity_usd: float | None
    volume_24h_usd: float | None
    market_cap_usd: float | None
    fdv_usd: float | None
    price_change_24h_pct: float | None
    buys_24h: int | None
    sells_24h: int | None
    discovery_sources: tuple[str, ...]


@dataclass(frozen=True)
class TokenRisk:
    mint_authority_revoked: bool | None
    freeze_authority_revoked: bool | None
    raw_largest_account_pct: float | None
    raw_top20_accounts_pct: float | None
    error: str | None = None


@dataclass(frozen=True)
class HistoryFeatures:
    observation_days: int
    range_position_90d: float | None
    return_30d_pct: float | None
    return_90d_pct: float | None
    maximum_drawdown_90d_pct: float | None


@dataclass(frozen=True)
class Decision:
    status: DecisionStatus
    score: float
    reasons: tuple[str, ...]
    estimated_round_trip_cost_bps: float | None
    history: HistoryFeatures
