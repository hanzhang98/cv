from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable

from .clients import GeckoTerminalClient, PublicAPIError, SolanaClient
from .config import AppConfig
from .models import DecisionStatus, PoolSnapshot, TokenRisk
from .scoring import evaluate, estimated_round_trip_cost_bps
from .storage import Store


def _merge_pool_snapshots(snapshots: Iterable[PoolSnapshot]) -> list[PoolSnapshot]:
    merged: dict[tuple[str, str], PoolSnapshot] = {}
    for snapshot in snapshots:
        key = (snapshot.network, snapshot.pool_address)
        current = merged.get(key)
        if current is None:
            merged[key] = snapshot
            continue
        sources = tuple(sorted(set(current.discovery_sources + snapshot.discovery_sources)))
        merged[key] = replace(snapshot, discovery_sources=sources)
    return list(merged.values())


def _passes_market_prefilter(snapshot: PoolSnapshot, config: AppConfig) -> bool:
    rules = config.eligibility
    return bool(
        snapshot.pool_created_at
        and (snapshot.observed_at - snapshot.pool_created_at).days >= rules.minimum_age_days
        and snapshot.liquidity_usd
        and snapshot.liquidity_usd >= rules.minimum_liquidity_usd
        and snapshot.volume_24h_usd
        and snapshot.volume_24h_usd >= rules.minimum_volume_24h_usd
    )


def run_daily_scan(
    config: AppConfig,
    now: datetime | None = None,
    gecko: GeckoTerminalClient | None = None,
    solana: SolanaClient | None = None,
) -> dict[str, int]:
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gecko = gecko or GeckoTerminalClient(config.discovery)
    solana = solana or SolanaClient(
        endpoint=config.risk.solana_rpc_url,
        user_agent=config.discovery.user_agent,
        request_interval_seconds=config.risk.request_interval_seconds,
        maximum_retries=config.risk.maximum_retries,
    )
    store = Store(config.database_path)
    run_id = store.start_run(observed_at)
    try:
        snapshots = gecko.discover(observed_at)
        discovered_addresses = {item.pool_address for item in snapshots}
        for row in store.open_signal_pools():
            if row["network"] != config.discovery.network or row["address"] in discovered_addresses:
                continue
            try:
                refreshed = gecko.get_pool(row["address"], observed_at)
            except PublicAPIError:
                refreshed = None
            if refreshed:
                snapshots.append(refreshed)

        snapshots = [
            snapshot
            for snapshot in _merge_pool_snapshots(snapshots)
            if snapshot.token_address not in config.discovery.excluded_token_addresses
        ]
        identifiers: dict[tuple[str, str], tuple[int, int]] = {}
        with store.transaction():
            for snapshot in snapshots:
                identifiers[(snapshot.network, snapshot.pool_address)] = store.save_snapshot(
                    run_id, snapshot
                )

        best_by_token: dict[int, tuple[PoolSnapshot, int]] = {}
        for snapshot in snapshots:
            token_id, pool_id = identifiers[(snapshot.network, snapshot.pool_address)]
            current = best_by_token.get(token_id)
            liquidity = snapshot.liquidity_usd or 0
            if current is None or liquidity > (current[0].liquidity_usd or 0):
                best_by_token[token_id] = (snapshot, pool_id)

        counts = {status.value: 0 for status in DecisionStatus}
        exit_costs: dict[int, float] = {}
        with store.transaction():
            for token_id, (snapshot, pool_id) in best_by_token.items():
                if _passes_market_prefilter(snapshot, config):
                    risk = solana.token_risk(snapshot.token_address)
                else:
                    risk = TokenRisk(
                        None,
                        None,
                        None,
                        None,
                        error="not requested because market prefilter failed",
                    )
                store.save_risk(run_id, token_id, risk)
                rows = store.daily_prices(
                    token_id, days=config.eligibility.minimum_forward_history_days
                )
                decision = evaluate(
                    snapshot=snapshot,
                    risk=risk,
                    daily_prices=[row["price_usd"] for row in rows],
                    label=store.label_for(token_id),
                    config=config.eligibility,
                    now=observed_at,
                )
                store.save_decision(run_id, token_id, decision)
                counts[decision.status.value] += 1
                if decision.estimated_round_trip_cost_bps is not None:
                    exit_costs[token_id] = decision.estimated_round_trip_cost_bps / 2
                if (
                    decision.status is DecisionStatus.PAPER_CANDIDATE
                    and snapshot.price_usd
                    and decision.estimated_round_trip_cost_bps is not None
                ):
                    store.maybe_open_paper_signal(
                        run_id=run_id,
                        token_id=token_id,
                        pool_id=pool_id,
                        observed_at=observed_at,
                        price_usd=snapshot.price_usd,
                        entry_cost_bps=decision.estimated_round_trip_cost_bps / 2,
                        cooldown_days=config.paper.signal_cooldown_days,
                    )
            store.mark_paper_signals(
                run_id=run_id,
                observed_at=observed_at,
                exit_cost_bps_by_token=exit_costs,
                stale_runs_before_zero=config.paper.stale_runs_before_zero,
                maximum_tracking_days=config.paper.maximum_tracking_days,
            )
        store.finish_run(run_id)
        return {
            "run_id": run_id,
            "pools_observed": len(snapshots),
            "tokens_observed": len(best_by_token),
            **counts,
        }
    except Exception as exc:
        store.finish_run(run_id, error=str(exc))
        raise
    finally:
        store.close()


def current_cost_bps(snapshot: PoolSnapshot, config: AppConfig) -> float | None:
    return estimated_round_trip_cost_bps(
        snapshot.liquidity_usd,
        config.eligibility.intended_order_usd,
        config.eligibility.base_round_trip_cost_bps,
    )
