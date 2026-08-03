from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analysis.scorer import IdeaScorer
from config import get_settings, load_sources, load_themes
from ingest.substack import SubstackIngester
from ingest.twitter import TwitterIngester
from models.ideas import RawItem, ScoredIdea, SourceType

# bot/src/pipeline.py → bot/
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def _parse_fixture_item(row: dict) -> RawItem:
    published = row.get("published_at")
    dt = None
    if published:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
    return RawItem(
        id=row["id"],
        source_type=SourceType(row.get("source_type", "fixture")),
        source_name=row.get("source_name", "fixture"),
        title=row["title"],
        summary=row.get("summary", ""),
        url=row.get("url", "https://example.com"),
        author=row.get("author"),
        published_at=dt,
        source_weight=float(row.get("source_weight", 1.0)),
        noise_bias=float(row.get("noise_bias", 0.0)),
        tags=list(row.get("tags") or []),
    )


def load_fixtures() -> list[RawItem]:
    path = FIXTURES / "sample_items.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_parse_fixture_item(row) for row in data]


class IdeaPipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.themes_cfg = load_themes()
        self.sources_cfg = load_sources()
        self.scorer = IdeaScorer(self.themes_cfg, self.sources_cfg)
        scoring = self.sources_cfg.get("scoring") or {}
        self.max_items = int(scoring.get("max_items_per_digest", 12))
        self.lookback_hours = int(scoring.get("lookback_hours", 72))

    async def collect_raw(self) -> list[RawItem]:
        if self.settings.is_demo:
            return load_fixtures()

        items: list[RawItem] = []
        substack = SubstackIngester(list(self.sources_cfg.get("substack") or []))
        items.extend(await substack.fetch_all())

        tw_cfg = self.sources_cfg.get("twitter") or {}
        twitter = TwitterIngester(
            bearer_token=self.settings.twitter_bearer_token,
            accounts=list(tw_cfg.get("accounts") or []),
            queries=list(tw_cfg.get("queries") or []),
        )
        if twitter.enabled:
            items.extend(await twitter.fetch_all())
        else:
            # Still include fixture Twitter examples so digests aren't Substack-only
            items.extend(
                [i for i in load_fixtures() if i.source_type == SourceType.TWITTER]
            )
        return items

    def _within_lookback(self, item: RawItem) -> bool:
        if not self.lookback_hours or self.lookback_hours <= 0:
            return True
        if item.published_at is None:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        pub = item.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return pub >= cutoff

    def _diversify(self, scored: list[ScoredIdea], limit: int, per_source: int = 2) -> list[ScoredIdea]:
        """Keep ranking but avoid one newsletter dominating the digest."""
        picked: list[ScoredIdea] = []
        counts: dict[str, int] = {}
        deferred: list[ScoredIdea] = []
        for idea in scored:
            src = idea.item.source_name
            if counts.get(src, 0) < per_source:
                picked.append(idea)
                counts[src] = counts.get(src, 0) + 1
            else:
                deferred.append(idea)
            if len(picked) >= limit:
                return picked
        for idea in deferred:
            if len(picked) >= limit:
                break
            picked.append(idea)
        return picked

    async def digest(
        self,
        theme_id: str | None = None,
        limit: int | None = None,
    ) -> list[ScoredIdea]:
        raw = await self.collect_raw()
        raw = [i for i in raw if self._within_lookback(i)]
        scored = self.scorer.score_many(raw)
        if theme_id:
            scored = [
                s
                for s in scored
                if any(h.theme_id == theme_id for h in s.theme_hits)
            ]
        n = limit or self.max_items
        return self._diversify(scored, n, per_source=2)

    def list_themes(self) -> list[tuple[str, str, str]]:
        themes = self.themes_cfg.get("themes") or {}
        return [
            (tid, spec.get("label", tid), spec.get("description", ""))
            for tid, spec in themes.items()
        ]
