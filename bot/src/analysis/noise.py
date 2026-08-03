from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class NoiseResult:
    noise_score: float  # 0..1 higher = more hype/meme
    quality_score: float  # 0..1 higher = more research-like
    signals: list[str]


def _count_hits(text: str, phrases: list[str]) -> list[str]:
    hits: list[str] = []
    lower = text.lower()
    for phrase in phrases:
        if phrase.lower() in lower:
            hits.append(phrase)
    return hits


class NoiseFilter:
    """WSB-style noise is kept but down-weighted.

    We never hard-drop purely because of meme language — crowdsourced retail
    sometimes surfaces real catalysts early. Instead we score and discount.
    """

    def __init__(self, noise_cfg: dict) -> None:
        signals = noise_cfg.get("noise_signals") or {}
        self.high = list(signals.get("high") or [])
        self.medium = list(signals.get("medium") or [])
        self.quality = list(signals.get("quality") or [])
        self._emoji_re = re.compile(r"[🚀💎🦍🌙]+")
        self._allcaps_re = re.compile(r"\b[A-Z]{4,}\b")

    def score(self, title: str, summary: str, noise_bias: float = 0.0) -> NoiseResult:
        text = f"{title}\n{summary}"
        high_hits = _count_hits(text, self.high)
        med_hits = _count_hits(text, self.medium)
        qual_hits = _count_hits(text, self.quality)

        noise = 0.0
        noise += min(0.55, 0.18 * len(high_hits))
        noise += min(0.30, 0.10 * len(med_hits))
        if self._emoji_re.search(text):
            noise += 0.15
            high_hits.append("rocket/diamond emoji")
        caps = self._allcaps_re.findall(title)
        if len(caps) >= 2:
            noise += 0.1
            high_hits.append("ALLCAPS")
        noise += max(0.0, min(0.5, noise_bias))
        noise = max(0.0, min(1.0, noise))

        quality = min(1.0, 0.15 * len(qual_hits))
        # Research tone offsets some noise
        noise = max(0.0, noise - 0.35 * quality)

        signals = [f"noise:{h}" for h in high_hits + med_hits] + [
            f"quality:{q}" for q in qual_hits
        ]
        return NoiseResult(noise_score=noise, quality_score=quality, signals=signals)
