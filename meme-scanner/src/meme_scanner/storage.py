from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .models import Decision, PoolSnapshot, TokenRisk

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY,
    network TEXT NOT NULL,
    address TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(network, address)
);

CREATE TABLE IF NOT EXISTS pools (
    id INTEGER PRIMARY KEY,
    network TEXT NOT NULL,
    address TEXT NOT NULL,
    token_id INTEGER NOT NULL REFERENCES tokens(id),
    quote_token_address TEXT NOT NULL,
    dex_id TEXT NOT NULL,
    created_at TEXT,
    UNIQUE(network, address)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    token_id INTEGER NOT NULL REFERENCES tokens(id),
    pool_id INTEGER NOT NULL REFERENCES pools(id),
    observed_at TEXT NOT NULL,
    price_usd REAL,
    liquidity_usd REAL,
    volume_24h_usd REAL,
    market_cap_usd REAL,
    fdv_usd REAL,
    price_change_24h_pct REAL,
    buys_24h INTEGER,
    sells_24h INTEGER,
    discovery_sources_json TEXT NOT NULL,
    UNIQUE(run_id, pool_id)
);

CREATE TABLE IF NOT EXISTS token_risks (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    token_id INTEGER NOT NULL REFERENCES tokens(id),
    mint_authority_revoked INTEGER,
    freeze_authority_revoked INTEGER,
    raw_largest_account_pct REAL,
    raw_top20_accounts_pct REAL,
    error TEXT,
    PRIMARY KEY(run_id, token_id)
);

CREATE TABLE IF NOT EXISTS labels (
    token_id INTEGER PRIMARY KEY REFERENCES tokens(id),
    category TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    labeled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    token_id INTEGER NOT NULL REFERENCES tokens(id),
    status TEXT NOT NULL,
    score REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    estimated_round_trip_cost_bps REAL,
    observation_days INTEGER NOT NULL,
    range_position_90d REAL,
    return_30d_pct REAL,
    return_90d_pct REAL,
    maximum_drawdown_90d_pct REAL,
    PRIMARY KEY(run_id, token_id)
);

CREATE TABLE IF NOT EXISTS paper_signals (
    id INTEGER PRIMARY KEY,
    token_id INTEGER NOT NULL REFERENCES tokens(id),
    pool_id INTEGER NOT NULL REFERENCES pools(id),
    opened_run_id INTEGER NOT NULL REFERENCES runs(id),
    opened_at TEXT NOT NULL,
    entry_price_usd REAL NOT NULL,
    entry_cost_bps REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    stale_runs INTEGER NOT NULL DEFAULT 0,
    closed_at TEXT,
    close_reason TEXT
);

CREATE TABLE IF NOT EXISTS paper_marks (
    signal_id INTEGER NOT NULL REFERENCES paper_signals(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    observed_at TEXT NOT NULL,
    price_usd REAL NOT NULL,
    estimated_exit_cost_bps REAL NOT NULL,
    net_return_pct REAL NOT NULL,
    assumed_zero INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(signal_id, run_id)
);

CREATE INDEX IF NOT EXISTS snapshots_token_time
    ON snapshots(token_id, observed_at);
CREATE INDEX IF NOT EXISTS decisions_status
    ON decisions(run_id, status);
"""


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def start_run(self, started_at: datetime) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs(started_at, status) VALUES (?, 'running')",
            (_iso(started_at),),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, error: str | None = None) -> None:
        self.connection.execute(
            """
            UPDATE runs SET completed_at = ?, status = ?, error = ?
            WHERE id = ?
            """,
            (
                _iso(datetime.now(timezone.utc)),
                "failed" if error else "completed",
                error,
                run_id,
            ),
        )
        self.connection.commit()

    def save_snapshot(self, run_id: int, snapshot: PoolSnapshot) -> tuple[int, int]:
        observed = _iso(snapshot.observed_at)
        self.connection.execute(
            """
            INSERT INTO tokens(network, address, symbol, name, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(network, address) DO UPDATE SET
                symbol = excluded.symbol,
                name = excluded.name,
                last_seen_at = excluded.last_seen_at
            """,
            (
                snapshot.network,
                snapshot.token_address,
                snapshot.token_symbol,
                snapshot.token_name,
                observed,
                observed,
            ),
        )
        token_id = int(
            self.connection.execute(
                "SELECT id FROM tokens WHERE network = ? AND address = ?",
                (snapshot.network, snapshot.token_address),
            ).fetchone()["id"]
        )
        self.connection.execute(
            """
            INSERT INTO pools(
                network, address, token_id, quote_token_address, dex_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(network, address) DO UPDATE SET
                token_id = excluded.token_id,
                quote_token_address = excluded.quote_token_address,
                dex_id = excluded.dex_id,
                created_at = COALESCE(pools.created_at, excluded.created_at)
            """,
            (
                snapshot.network,
                snapshot.pool_address,
                token_id,
                snapshot.quote_token_address,
                snapshot.dex_id,
                _iso(snapshot.pool_created_at),
            ),
        )
        pool_id = int(
            self.connection.execute(
                "SELECT id FROM pools WHERE network = ? AND address = ?",
                (snapshot.network, snapshot.pool_address),
            ).fetchone()["id"]
        )
        self.connection.execute(
            """
            INSERT INTO snapshots(
                run_id, token_id, pool_id, observed_at, price_usd, liquidity_usd,
                volume_24h_usd, market_cap_usd, fdv_usd, price_change_24h_pct,
                buys_24h, sells_24h, discovery_sources_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, pool_id) DO UPDATE SET
                price_usd = excluded.price_usd,
                liquidity_usd = excluded.liquidity_usd,
                volume_24h_usd = excluded.volume_24h_usd,
                market_cap_usd = excluded.market_cap_usd,
                fdv_usd = excluded.fdv_usd,
                price_change_24h_pct = excluded.price_change_24h_pct,
                buys_24h = excluded.buys_24h,
                sells_24h = excluded.sells_24h,
                discovery_sources_json = excluded.discovery_sources_json
            """,
            (
                run_id,
                token_id,
                pool_id,
                observed,
                snapshot.price_usd,
                snapshot.liquidity_usd,
                snapshot.volume_24h_usd,
                snapshot.market_cap_usd,
                snapshot.fdv_usd,
                snapshot.price_change_24h_pct,
                snapshot.buys_24h,
                snapshot.sells_24h,
                json.dumps(snapshot.discovery_sources),
            ),
        )
        return token_id, pool_id

    def save_risk(self, run_id: int, token_id: int, risk: TokenRisk) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO token_risks VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                token_id,
                risk.mint_authority_revoked,
                risk.freeze_authority_revoked,
                risk.raw_largest_account_pct,
                risk.raw_top20_accounts_pct,
                risk.error,
            ),
        )

    def set_label(self, network: str, address: str, category: str, note: str) -> None:
        token = self.connection.execute(
            "SELECT id FROM tokens WHERE network = ? AND address = ?",
            (network, address),
        ).fetchone()
        if token is None:
            raise ValueError("token has not been observed by the scanner")
        self.connection.execute(
            """
            INSERT INTO labels(token_id, category, note, labeled_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(token_id) DO UPDATE SET
                category = excluded.category,
                note = excluded.note,
                labeled_at = excluded.labeled_at
            """,
            (
                token["id"],
                category,
                note,
                _iso(datetime.now(timezone.utc)),
            ),
        )
        self.connection.commit()

    def label_for(self, token_id: int) -> str | None:
        row = self.connection.execute(
            "SELECT category FROM labels WHERE token_id = ?", (token_id,)
        ).fetchone()
        return str(row["category"]) if row else None

    def daily_prices(self, token_id: int, days: int = 90) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            WITH ranked AS (
                SELECT
                    date(observed_at) AS day,
                    observed_at,
                    price_usd,
                    liquidity_usd,
                    ROW_NUMBER() OVER (
                        PARTITION BY date(observed_at)
                        ORDER BY liquidity_usd DESC NULLS LAST
                    ) AS ranking
                FROM snapshots
                WHERE token_id = ? AND price_usd > 0
            )
            SELECT day, observed_at, price_usd, liquidity_usd
            FROM ranked WHERE ranking = 1
            ORDER BY observed_at DESC LIMIT ?
            """,
            (token_id, days),
        ).fetchall()[::-1]

    def save_decision(self, run_id: int, token_id: int, decision: Decision) -> None:
        history = decision.history
        self.connection.execute(
            """
            INSERT OR REPLACE INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                token_id,
                decision.status,
                decision.score,
                json.dumps(decision.reasons),
                decision.estimated_round_trip_cost_bps,
                history.observation_days,
                history.range_position_90d,
                history.return_30d_pct,
                history.return_90d_pct,
                history.maximum_drawdown_90d_pct,
            ),
        )

    def latest_run_report(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                t.symbol, t.name, t.address, d.status, d.score, d.reasons_json,
                d.estimated_round_trip_cost_bps, s.liquidity_usd, s.volume_24h_usd,
                s.price_usd
            FROM decisions d
            JOIN tokens t ON t.id = d.token_id
            JOIN snapshots s ON s.run_id = d.run_id AND s.token_id = d.token_id
            WHERE d.run_id = (SELECT MAX(id) FROM runs WHERE status = 'completed')
              AND s.id = (
                SELECT s2.id FROM snapshots s2
                WHERE s2.run_id = s.run_id AND s2.token_id = s.token_id
                ORDER BY s2.liquidity_usd DESC NULLS LAST LIMIT 1
              )
            ORDER BY d.status DESC, d.score DESC
            """
        ).fetchall()

    def maybe_open_paper_signal(
        self,
        run_id: int,
        token_id: int,
        pool_id: int,
        observed_at: datetime,
        price_usd: float,
        entry_cost_bps: float,
        cooldown_days: int,
    ) -> None:
        recent = self.connection.execute(
            """
            SELECT 1 FROM paper_signals
            WHERE token_id = ?
              AND julianday(?) - julianday(opened_at) < ?
            LIMIT 1
            """,
            (token_id, _iso(observed_at), cooldown_days),
        ).fetchone()
        if recent is None:
            self.connection.execute(
                """
                INSERT INTO paper_signals(
                    token_id, pool_id, opened_run_id, opened_at,
                    entry_price_usd, entry_cost_bps
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token_id, pool_id, run_id, _iso(observed_at), price_usd, entry_cost_bps),
            )

    def open_signal_pools(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT DISTINCT p.address, p.network
            FROM paper_signals ps
            JOIN pools p ON p.id = ps.pool_id
            WHERE ps.status = 'open'
            """
        ).fetchall()

    def mark_paper_signals(
        self,
        run_id: int,
        observed_at: datetime,
        exit_cost_bps_by_token: dict[int, float],
        stale_runs_before_zero: int,
        maximum_tracking_days: int,
    ) -> None:
        signals = self.connection.execute(
            "SELECT * FROM paper_signals WHERE status = 'open'"
        ).fetchall()
        for signal in signals:
            snapshot = self.connection.execute(
                """
                SELECT price_usd FROM snapshots
                WHERE run_id = ? AND token_id = ? AND price_usd > 0
                ORDER BY liquidity_usd DESC NULLS LAST LIMIT 1
                """,
                (run_id, signal["token_id"]),
            ).fetchone()
            age_days = (
                observed_at - datetime.fromisoformat(signal["opened_at"])
            ).total_seconds() / 86400
            if snapshot is None:
                stale = int(signal["stale_runs"]) + 1
                self.connection.execute(
                    "UPDATE paper_signals SET stale_runs = ? WHERE id = ?",
                    (stale, signal["id"]),
                )
                if stale < stale_runs_before_zero:
                    continue
                price = 0.0
                assumed_zero = 1
                close_reason = "missing_for_configured_stale_runs"
            else:
                price = float(snapshot["price_usd"])
                assumed_zero = 0
                close_reason = "maximum_tracking_period" if age_days >= maximum_tracking_days else None
                self.connection.execute(
                    "UPDATE paper_signals SET stale_runs = 0 WHERE id = ?",
                    (signal["id"],),
                )

            exit_cost = exit_cost_bps_by_token.get(signal["token_id"], 0.0)
            gross_return = price / float(signal["entry_price_usd"]) - 1
            net_return_pct = (
                gross_return * 100
                - float(signal["entry_cost_bps"]) / 100
                - exit_cost / 100
            )
            self.connection.execute(
                """
                INSERT OR REPLACE INTO paper_marks VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal["id"],
                    run_id,
                    _iso(observed_at),
                    price,
                    exit_cost,
                    net_return_pct,
                    assumed_zero,
                ),
            )
            if close_reason:
                self.connection.execute(
                    """
                    UPDATE paper_signals
                    SET status = 'closed', closed_at = ?, close_reason = ?
                    WHERE id = ?
                    """,
                    (_iso(observed_at), close_reason, signal["id"]),
                )
