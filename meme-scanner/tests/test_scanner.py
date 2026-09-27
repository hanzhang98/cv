from datetime import datetime, timedelta, timezone
import json

from meme_scanner.config import AppConfig
from meme_scanner.models import PoolSnapshot
from meme_scanner.scanner import run_daily_scan
from meme_scanner.storage import Store


class FakeGecko:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def discover(self, observed_at):
        return self.snapshots

    def get_pool(self, pool_address, observed_at):
        raise AssertionError("there should be no open signals on the first run")


class RiskMustNotRun:
    def token_risk(self, token_address):
        raise AssertionError("risk RPC should follow the cheap market prefilter")


def test_scan_persists_rejected_tokens_and_reasons(tmp_path):
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    low_liquidity = PoolSnapshot(
        network="solana",
        pool_address="pool",
        token_address="mint",
        token_symbol="NEW",
        token_name="New token",
        quote_token_address="sol",
        dex_id="dex",
        observed_at=now,
        pool_created_at=now - timedelta(days=2),
        price_usd=0.01,
        liquidity_usd=10_000,
        volume_24h_usd=5_000,
        market_cap_usd=100_000,
        fdv_usd=100_000,
        price_change_24h_pct=20,
        buys_24h=10,
        sells_24h=5,
        discovery_sources=("new_pools",),
    )
    config = AppConfig(database_path=str(tmp_path / "scanner.sqlite3"))

    summary = run_daily_scan(
        config,
        now=now,
        gecko=FakeGecko([low_liquidity]),
        solana=RiskMustNotRun(),
    )

    assert summary["rejected"] == 1
    store = Store(config.database_path)
    try:
        report = store.latest_run_report()
        assert len(report) == 1
        reasons = json.loads(report[0]["reasons_json"])
        assert "pool_too_new" in reasons
        assert "insufficient_liquidity" in reasons
        assert "insufficient_24h_volume" in reasons
    finally:
        store.close()
