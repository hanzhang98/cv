from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    SUBSTACK = "substack"
    TWITTER = "twitter"
    FIXTURE = "fixture"


class ThemeHit(BaseModel):
    theme_id: str
    label: str
    matched_keywords: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    headwinds: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)


class RawItem(BaseModel):
    id: str
    source_type: SourceType
    source_name: str
    title: str
    summary: str = ""
    url: str
    author: str | None = None
    published_at: datetime | None = None
    source_weight: float = 1.0
    noise_bias: float = 0.0
    tags: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ScoredIdea(BaseModel):
    item: RawItem
    score: float
    theme_hits: list[ThemeHit] = Field(default_factory=list)
    noise_score: float = 0.0
    quality_score: float = 0.0
    rationale: str = ""

    @property
    def primary_theme(self) -> str | None:
        if not self.theme_hits:
            return None
        return self.theme_hits[0].label

    def telegram_html(self) -> str:
        themes = ", ".join(h.label for h in self.theme_hits[:2]) or "General"
        cats = []
        heads = []
        tickers: list[str] = []
        for h in self.theme_hits:
            cats.extend(h.catalysts)
            heads.extend(h.headwinds)
            tickers.extend(h.tickers)
        cats = list(dict.fromkeys(cats))[:3]
        heads = list(dict.fromkeys(heads))[:3]
        tickers = list(dict.fromkeys(tickers))[:6]

        lines = [
            f"<b>{_esc(self.item.title)}</b>",
            f"Theme: {_esc(themes)} · Score: {self.score:.2f}",
            f"Source: {_esc(self.item.source_name)} ({self.item.source_type.value})",
        ]
        if tickers:
            lines.append(f"Tickers: {_esc(', '.join(tickers))}")
        if cats:
            lines.append(f"Catalysts: {_esc(', '.join(cats))}")
        if heads:
            lines.append(f"Headwinds: {_esc(', '.join(heads))}")
        if self.rationale:
            lines.append(_esc(self.rationale))
        if self.noise_score >= 0.4:
            lines.append(f"<i>Noise flag {self.noise_score:.2f} — down-weighted</i>")
        lines.append(f'<a href="{_esc(self.item.url)}">Open</a>')
        return "\n".join(lines)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
