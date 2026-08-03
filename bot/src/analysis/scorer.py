from __future__ import annotations

from datetime import datetime, timezone

from analysis.noise import NoiseFilter
from analysis.themes import ThemeMatcher
from models.ideas import RawItem, ScoredIdea


class IdeaScorer:
    def __init__(self, themes_cfg: dict, sources_cfg: dict) -> None:
        self.matcher = ThemeMatcher(themes_cfg)
        self.noise = NoiseFilter(themes_cfg)
        scoring = sources_cfg.get("scoring") or {}
        self.min_score = float(scoring.get("min_score_to_surface", 0.35))
        self.noise_penalty_cap = float(scoring.get("noise_penalty_cap", 0.55))
        self.source_weight_floor = float(scoring.get("source_weight_floor", 0.2))
        self.recency_full_boost_hours = float(scoring.get("recency_full_boost_hours", 48))
        self.recency_half_life_hours = float(scoring.get("recency_half_life_hours", 168))
        self.recency_max_boost = float(scoring.get("recency_max_boost", 0.18))

    def _recency_boost(self, item: RawItem, now: datetime | None = None) -> tuple[float, str | None]:
        if item.published_at is None:
            return 0.0, None
        now = now or datetime.now(timezone.utc)
        pub = item.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - pub.astimezone(timezone.utc)).total_seconds() / 3600.0)
        if age_h <= self.recency_full_boost_hours:
            boost = self.recency_max_boost
            note = f"Fresh ({age_h:.0f}h)."
        else:
            # Exponential decay after the full-boost window.
            over = age_h - self.recency_full_boost_hours
            half = max(1.0, self.recency_half_life_hours)
            boost = self.recency_max_boost * (0.5 ** (over / half))
            days = age_h / 24.0
            note = f"{days:.1f}d old."
        return boost, note

    def score_one(self, item: RawItem, now: datetime | None = None) -> ScoredIdea | None:
        themes = self.matcher.match(item)
        noise = self.noise.score(item.title, item.summary, item.noise_bias)

        # Base: thematic relevance (sublinear so scores don't all pin at 1.0)
        if themes:
            kw_hits = sum(len(t.matched_keywords) for t in themes)
            theme_strength = min(0.92, 0.28 + 0.08 * kw_hits + 0.05 * (len(themes) - 1))
        else:
            # Unthemed items can still surface if quality is high
            theme_strength = 0.12 * noise.quality_score

        source_w = max(self.source_weight_floor, min(1.15, item.source_weight))
        noise_penalty = min(self.noise_penalty_cap, noise.noise_score * 0.75)
        quality_boost = 0.2 * noise.quality_score
        recency_boost, recency_note = self._recency_boost(item, now=now)

        # Leave headroom so recency can change rank (don't pin everything at 1.0).
        base = (theme_strength * source_w) + quality_boost
        base = min(0.82, base)
        raw = base + recency_boost
        # Never fully erase a thematic hit — WSB-style posts stay visible but ranked last.
        if themes:
            floor = max(0.08, min(0.25, theme_strength * 0.2))
            score = max(floor, raw * 0.35, raw - noise_penalty)
        else:
            score = raw - noise_penalty
        score = max(0.0, min(1.0, score))

        # Keep thematic (even noisy) ideas with low weight; only hard-drop
        # unthemed junk or near-zero scores.
        if not themes and score < self.min_score:
            return None
        if not themes and noise.noise_score > 0.55:
            return None

        rationale_parts: list[str] = []
        if themes:
            top = themes[0]
            rationale_parts.append(
                f"Matched {top.label} via {', '.join(top.matched_keywords[:4])}."
            )
        if noise.noise_score >= 0.35:
            rationale_parts.append(
                f"Retail/hype language detected (noise {noise.noise_score:.2f}); kept with lower weight."
            )
        if noise.quality_score >= 0.3:
            rationale_parts.append("Research-like framing boosted confidence.")
        if recency_note and recency_boost >= 0.05:
            rationale_parts.append(recency_note)

        return ScoredIdea(
            item=item,
            score=score,
            theme_hits=themes,
            noise_score=noise.noise_score,
            quality_score=noise.quality_score,
            rationale=" ".join(rationale_parts),
        )

    def score_many(self, items: list[RawItem]) -> list[ScoredIdea]:
        now = datetime.now(timezone.utc)
        scored: list[ScoredIdea] = []
        seen: set[str] = set()
        for item in items:
            key = item.url.strip().lower() or item.id
            if key in seen:
                continue
            seen.add(key)
            idea = self.score_one(item, now=now)
            if idea is not None:
                scored.append(idea)
        # Prefer higher score; break ties with newer publish time.
        scored.sort(
            key=lambda x: (
                x.score,
                x.item.published_at.timestamp() if x.item.published_at else 0.0,
            ),
            reverse=True,
        )
        return scored
