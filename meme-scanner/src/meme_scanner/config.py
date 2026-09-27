from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar
import tomllib

T = TypeVar("T")


@dataclass(frozen=True)
class DiscoveryConfig:
    network: str = "solana"
    pages_per_source: int = 1
    sources: tuple[str, ...] = ("pools", "trending_pools", "new_pools")
    request_interval_seconds: float = 6.1
    user_agent: str = "meme-scanner/0.1 (forward research journal)"
    excluded_token_addresses: tuple[str, ...] = (
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD5cYtJbftrmtZDEVV1z6Y",
    )


@dataclass(frozen=True)
class EligibilityConfig:
    minimum_age_days: int = 90
    minimum_liquidity_usd: float = 1_000_000
    minimum_volume_24h_usd: float = 500_000
    intended_order_usd: float = 1_000
    base_round_trip_cost_bps: float = 100
    maximum_round_trip_cost_bps: float = 200
    minimum_forward_history_days: int = 90
    maximum_range_position: float = 0.25
    require_community_label: bool = True
    require_revoked_authorities: bool = True


@dataclass(frozen=True)
class RiskConfig:
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    request_interval_seconds: float = 0.5
    maximum_retries: int = 4


@dataclass(frozen=True)
class PaperConfig:
    signal_cooldown_days: int = 30
    stale_runs_before_zero: int = 3
    maximum_tracking_days: int = 90


@dataclass(frozen=True)
class AppConfig:
    database_path: str = "data/meme_scanner.sqlite3"
    discovery: DiscoveryConfig = DiscoveryConfig()
    eligibility: EligibilityConfig = EligibilityConfig()
    risk: RiskConfig = RiskConfig()
    paper: PaperConfig = PaperConfig()


def _section(cls: type[T], values: dict[str, Any]) -> T:
    allowed = {field.name for field in fields(cls)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"unknown {cls.__name__} settings: {sorted(unknown)}")
    normalized = dict(values)
    if cls is DiscoveryConfig and "sources" in normalized:
        normalized["sources"] = tuple(normalized["sources"])
    if cls is DiscoveryConfig and "excluded_token_addresses" in normalized:
        normalized["excluded_token_addresses"] = tuple(
            normalized["excluded_token_addresses"]
        )
    return cls(**normalized)


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig()
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)
    allowed = {"database_path", "discovery", "eligibility", "risk", "paper"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"unknown top-level settings: {sorted(unknown)}")
    return AppConfig(
        database_path=raw.get("database_path", AppConfig.database_path),
        discovery=_section(DiscoveryConfig, raw.get("discovery", {})),
        eligibility=_section(EligibilityConfig, raw.get("eligibility", {})),
        risk=_section(RiskConfig, raw.get("risk", {})),
        paper=_section(PaperConfig, raw.get("paper", {})),
    )
