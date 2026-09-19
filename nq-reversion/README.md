# NQ intraday mean-reversion research

This is a research and manual-alert toolkit, not a claim that an edge exists.
It tests two pre-registered hypotheses on 1-minute NQ futures bars:

1. **Asian shock fade** — between 19:00 and 02:55 New York time, fade a
   one-minute move only when it is both at least 8 points and 3 trailing
   standard deviations, and price is at least 6 points from 60-minute VWAP.
2. **US-open rejection** — fade an overnight move of at least 35 points only
   after 09:30–09:34 rejects at least 35% of its opening range (and at least
   8 points). This avoids blindly fading price discovery.

Entries occur at the next bar's open. Stops use trailing ATR with fixed floors,
targets are trailing/overnight VWAP, and time stops are 12 and 25 minutes.
Default results include one tick of adverse slippage on each market fill,
$2.50 commission per side, and NQ's $20 point value. If both stop and target
occur in one OHLC bar, the stop is assumed to occur first.

## Set up

Python 3.11 or newer:

```bash
cd nq-reversion
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test,moomoo]'
```

Moomoo's SDK does not authenticate with a simple API key. Install and log in
to [OpenD](https://openapi.moomoo.com/moomoo-api-doc/en/quick/opend-base.html),
enable its local API port (normally `127.0.0.1:11111`), and ensure the account
has CME futures quote permission. OpenD should remain on the same machine as
this command. No account password or trading unlock password is stored here.

Download an **exact** contract:

```bash
nq-reversion download \
  --symbol US.NQ2612 \
  --start 2026-06-15 \
  --end 2026-09-18 \
  --output data/NQ2612.csv
```

Moomoo symbols are expiry-specific (`US.NQyymm`). The downloader rejects a
`main`/continuous symbol: unrecorded roll adjustments and overlapping
contracts can look like mean reversion. Research each liquid front contract,
then combine trade results—not raw overlapping bars. Confirm the exact current
symbol in Moomoo before downloading.

## Run

Moomoo futures timestamps are exchange-local and may be timezone-naive. Make
the source timezone explicit:

```bash
nq-reversion backtest \
  --csv data/NQ2612.csv \
  --source-timezone America/Chicago \
  --strategy all \
  --output-dir results/NQ2612
```

The command writes `trades.csv` and `summary.json`. A generic CSV can also be
used with columns `time` (or `time_key`), `open`, `high`, `low`, `close`, and
`volume`.

## Validation protocol

Do not tune thresholds on the full sample.

1. Use at least two years spanning different volatility regimes and keep the
   most recent six months untouched.
2. Develop on older contracts, lock parameters, and evaluate the untouched
   contracts once.
3. Report each contract and each strategy separately. Require positive
   expectancy after doubling the default slippage, not just in aggregate.
4. Inspect results around US CPI, NFP, FOMC, contract rolls, half-days, and the
   daylight-saving mismatch weeks. Excluding news after seeing losses is
   lookahead; define exclusions before the final test.
5. Replay or paper trade at least 50 signals. One-minute OHLC cannot determine
   queue position or the path within a bar.

The defaults are intentionally hypotheses, not optimized parameters. A small
number of trades, unstable contract-by-contract results, or failure under
two-tick slippage means there is not enough evidence to trade it.

## Manual execution in IBKR

Use the active NQ or MNQ contract in Trader Workstation and verify the
multiplier: NQ is $20/point; MNQ is $2/point. Before each trade:

- skip if the contract, session clock, or economic-news status is uncertain;
- calculate size from the stop: `contracts = floor(risk_budget /
  (stop_points * point_value + estimated_costs))`;
- enter only after the signal bar closes, with a bracket order;
- place the stop immediately and never widen it;
- use the strategy target and time stop; do not average down.

For manual trading, the clean next step is a read-only live signal screen fed
by OpenD, while order placement remains in IBKR. Automated cross-broker order
routing should wait until the historical and paper results survive the
protocol above.

## Options-flow extension

Options delta flow is deliberately not in version one. Raw option volume is
not signed dealer flow, and zero-DTE activity can be both hedging and
speculation. A defensible second phase would snapshot the NDX/QQQ option chain,
infer trade direction from quotes, estimate net delta/gamma exposure, and test
whether the base signals behave differently near high-gamma strikes. That
requires synchronized quote/trade data and should be evaluated as a
pre-declared filter—not added after inspecting losing trades.
