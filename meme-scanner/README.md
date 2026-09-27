# Forward-only memecoin scanner

This project records what a scanner could actually see each day. It is designed
to prevent a backtest from silently selecting only tokens that survived.
It never holds wallet keys, routes orders, or represents a token as safe.

## What it records

Each run takes the explicitly defined union of the first configured pages of
Solana's:

- top pools;
- trending pools;
- new pools.

These are public GeckoTerminal endpoints. Every returned pool is stored,
including every rejection and its reason. The universe is therefore
reproducible but **not the entire Solana token universe**. Increasing
`pages_per_source` broadens it and increases API usage.

For tokens that pass inexpensive market checks, the scanner also requests:

- mint and freeze authority status from Solana RPC;
- raw largest-account concentration;
- rolling features calculated only from snapshots already collected locally.

Raw token-account concentration includes AMM, burn, treasury, and exchange
accounts. It is evidence for manual review, not a holder-distribution verdict.

## Eligibility lifecycle

1. **Rejected:** fails age, liquidity, volume, cost, or authority rules.
2. **Watchlist:** passes those rules but lacks 90 distinct forward observation
   days, is not near the bottom quarter of its observed 90-day range, lacks
   risk data, or has not been manually labeled `community`.
3. **Paper candidate:** passes every rule after enough forward data exists.

No token can become a paper candidate on the first run. This is intentional.
Manual labels are review gates, not alpha labels. Review the contract address,
authority data, holder identities, LP custody, wash trading, and social claims
before applying `community`.

## Costs and failure handling

The default cost estimate is:

```text
100 bps base round trip + 4 × intended_order_usd / pool_liquidity_usd
```

The impact term approximates entry and exit through a constant-product pool.
It remains an estimate, so later analysis should stress it upward.

Paper signals are independent research cohorts, not a portfolio or rotation
strategy. They are marked daily for 90 days. If a held token cannot be priced
for three scan runs, its paper mark is forced to zero. Actual rotation logic is
deliberately deferred until the forward dataset exists.

## Install and run

Python 3.11 or newer:

```bash
cd meme-scanner
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp config.example.toml config.toml

meme-scanner --config config.toml scan
meme-scanner --config config.toml report --status watchlist
```

After reviewing a token by contract address:

```bash
meme-scanner --config config.toml label \
  --address SOLANA_MINT_ADDRESS \
  --category community \
  --note "Manual review date and evidence"
```

Run once per UTC day from a machine with persistent storage. For example, a
local cron entry at 00:15 UTC can call:

```cron
15 0 * * * cd /absolute/path/meme-scanner && .venv/bin/meme-scanner --config config.toml scan >> data/scanner.log 2>&1
```

Back up `data/meme_scanner.sqlite3`. Do not run the database from ephemeral CI:
losing old rejected tokens recreates the survivorship bias this tool exists to
avoid.

## Data limitations

- Public APIs can change, rate-limit, or omit pools.
- Market cap and volume can be manipulated.
- Current public data cannot reconstruct a complete historical universe.
- A public wallet does not establish that it is a trader's only wallet.
- A community label does not prevent rugs, exploits, or a permanent collapse.

The database becomes useful because it accumulates contemporaneous observations
from this point forward. It cannot make a trustworthy retrospective universe
appear today.
