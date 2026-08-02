# Investment Ideas Telegram Bot

Crowdsources thematic investment ideas from **Substack** and **Twitter/X**, scores them for catalysts / headwinds / buy-side positioning, and down-weights WSB-style noise without deleting it.

## What it does

1. **Ingest** — Substack RSS (primary starter) + Twitter recent search when a bearer token is set.
2. **Theme match** — Configurable maps in `config/themes.yaml` (e.g. CXMT → memory semis, Kimi → AI infra, 13F/crowded trades → positioning).
3. **Noise filter** — Meme/hype language and low-quality accounts get a penalty; research tone gets a boost. Retail chatter can still surface early catalysts, just ranked lower.
4. **Deliver** — Telegram commands (`/ideas`, `/theme`, `/digest`) or CLI digest for local use.

Demo mode ships with fixtures so you can try scoring without API keys.

## Quick start

```bash
cd bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Local digest (no Telegram token needed; uses fixtures in BOT_MODE=demo)
./run_cli.sh digest
./run_cli.sh themes
./run_cli.sh digest --theme memory_semiconductors

# Tests
pytest -q
```

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and put the token in `.env` as `TELEGRAM_BOT_TOKEN`.
2. Optional: set `TELEGRAM_ALLOWED_CHAT_IDS` to your user/chat id.
3. Run:

```bash
./run_bot.sh
```

Then message the bot: `/ideas`, `/themes`, `/theme ai_models_infra`, `/status`.

### Live sources

In `.env`:

```
BOT_MODE=live
TWITTER_BEARER_TOKEN=...   # optional; without it, live Substack + Twitter fixtures
```

Edit feeds and handles in `config/sources.yaml`. Edit thematic keywords in `config/themes.yaml`.

## Scoring (starter heuristic)

`score ≈ theme_strength × source_weight + quality_boost − noise_penalty`

- Theme strength grows with keyword hits (CXMT, HBM, Kimi, 13F, …).
- Source weight favors Semianalysis-style feeds; WSB/zerohedge-style handles start lower and often carry `noise_bias`.
- Noise never hard-drops by itself (cap on penalty) so meme posts with a real ticker/theme can still appear, labeled and down-weighted.

## Layout

```
bot/
  config/themes.yaml    # themes, catalysts, headwinds, noise lexicon
  config/sources.yaml   # Substack feeds, Twitter accounts/queries
  fixtures/             # demo articles/tweets
  src/
    analysis/           # theme match, noise, scorer
    ingest/             # substack RSS, twitter API
    bot/main.py         # Telegram app
    cli.py              # terminal digest
    pipeline.py         # glue
  tests/
```

## Roadmap (natural next steps)

- Embedding / LLM re-rank for “is this actually an investable variant view?”
- Persistent store + dedupe across days; scheduled `/digest` push to a channel
- More sources: Seeking Alpha RSS, company IR, 13F parsers
- Explicit ticker extraction + simple price/context hooks
- Per-user watchlists and theme subscriptions in Telegram

Not financial advice — research toy / workflow assistant.
