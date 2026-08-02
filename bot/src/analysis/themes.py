from __future__ import annotations

import re
from dataclasses import dataclass

from models.ideas import RawItem, ThemeHit


@dataclass
class ThemeDef:
    theme_id: str
    label: str
    description: str
    keywords: list[str]
    tickers: list[str]
    catalysts: list[str]
    headwinds: list[str]


def _compile_keyword(kw: str) -> re.Pattern[str]:
    # Word-ish match; allow tickers / acronyms case-insensitive.
    escaped = re.escape(kw)
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


class ThemeMatcher:
    def __init__(self, themes_cfg: dict) -> None:
        raw = themes_cfg.get("themes") or {}
        self.themes: list[ThemeDef] = []
        for theme_id, spec in raw.items():
            self.themes.append(
                ThemeDef(
                    theme_id=theme_id,
                    label=spec.get("label", theme_id),
                    description=spec.get("description", ""),
                    keywords=list(spec.get("keywords") or []),
                    tickers=list(spec.get("tickers") or []),
                    catalysts=list(spec.get("catalysts") or []),
                    headwinds=list(spec.get("headwinds") or []),
                )
            )
        self._kw_patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = {
            t.theme_id: [(kw, _compile_keyword(kw)) for kw in t.keywords]
            for t in self.themes
        }
        self._cat_patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = {
            t.theme_id: [(c, _compile_keyword(c)) for c in t.catalysts]
            for t in self.themes
        }
        self._head_patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = {
            t.theme_id: [(h, _compile_keyword(h)) for h in t.headwinds]
            for t in self.themes
        }

    def match(self, item: RawItem) -> list[ThemeHit]:
        text = f"{item.title}\n{item.summary}"
        hits: list[ThemeHit] = []
        for theme in self.themes:
            matched = [
                kw
                for kw, pat in self._kw_patterns[theme.theme_id]
                if pat.search(text)
            ]
            if not matched:
                continue
            cats = [
                c
                for c, pat in self._cat_patterns[theme.theme_id]
                if pat.search(text)
            ]
            heads = [
                h
                for h, pat in self._head_patterns[theme.theme_id]
                if pat.search(text)
            ]
            # Surface theme-level catalyst/headwind labels when keywords imply them
            if not cats and any(
                k.lower() in {"cxmt", "hbm", "hbm3", "hbm3e", "pricing upcycle"}
                for k in matched
            ):
                cats = list(theme.catalysts[:2])
            if not heads and any(
                "oversupply" in k.lower() or "competition" in k.lower() for k in matched
            ):
                heads = list(theme.headwinds[:2])

            hits.append(
                ThemeHit(
                    theme_id=theme.theme_id,
                    label=theme.label,
                    matched_keywords=matched,
                    catalysts=cats or list(theme.catalysts[:1]),
                    headwinds=heads or list(theme.headwinds[:1]),
                    tickers=[str(t) for t in theme.tickers],
                )
            )
        # Prefer themes with more keyword hits
        hits.sort(key=lambda h: len(h.matched_keywords), reverse=True)
        return hits
