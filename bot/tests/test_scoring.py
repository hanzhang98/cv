from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis.noise import NoiseFilter
from analysis.scorer import IdeaScorer
from analysis.themes import ThemeMatcher
from config import load_sources, load_themes
from models.ideas import RawItem, SourceType
from pipeline import IdeaPipeline, load_fixtures


@pytest.fixture
def themes_cfg():
    return load_themes()


@pytest.fixture
def sources_cfg():
    return load_sources()


def test_theme_match_cxmt_memory(themes_cfg):
    matcher = ThemeMatcher(themes_cfg)
    item = RawItem(
        id="1",
        source_type=SourceType.SUBSTACK,
        source_name="t",
        title="CXMT DRAM ramp pressures commodity memory pricing",
        summary="HBM allocation still tight for AI servers.",
        url="https://example.com/1",
    )
    hits = matcher.match(item)
    assert hits
    assert hits[0].theme_id == "memory_semiconductors"
    assert "CXMT" in hits[0].matched_keywords or any(
        "CXMT" in k for k in hits[0].matched_keywords
    )


def test_theme_match_kimi_ai(themes_cfg):
    matcher = ThemeMatcher(themes_cfg)
    item = RawItem(
        id="2",
        source_type=SourceType.TWITTER,
        source_name="@x",
        title="Kimi model release spurs LLM inference demand",
        summary="Moonshot AI and hyperscaler AI capex.",
        url="https://example.com/2",
    )
    hits = matcher.match(item)
    assert any(h.theme_id == "ai_models_infra" for h in hits)


def test_noise_downweights_wsb_but_keeps(themes_cfg, sources_cfg):
    scorer = IdeaScorer(themes_cfg, sources_cfg)
    noisy = RawItem(
        id="3",
        source_type=SourceType.TWITTER,
        source_name="@WSBmod",
        title="MU TO THE MOON 🚀 YOLO diamond hands",
        summary="guaranteed 100x tendies ape buy Micron memory HBM",
        url="https://example.com/3",
        source_weight=0.25,
        noise_bias=0.7,
    )
    clean = RawItem(
        id="4",
        source_type=SourceType.SUBSTACK,
        source_name="Semianalysis",
        title="CXMT vs Micron: HBM allocation and DRAM pricing thesis",
        summary="Variant perception on memory upcycle. Catalyst: HBM scarcity. Headwind: China oversupply.",
        url="https://example.com/4",
        source_weight=1.1,
    )
    s_noisy = scorer.score_one(noisy)
    s_clean = scorer.score_one(clean)
    assert s_clean is not None
    # Noisy memory chatter may still score if thematic, but below research source
    if s_noisy is not None:
        assert s_noisy.noise_score > s_clean.noise_score
        assert s_noisy.score < s_clean.score


def test_noise_filter_quality_offsets(themes_cfg):
    nf = NoiseFilter(themes_cfg)
    r = nf.score(
        "Hedge fund positioning and 13F crowded trade",
        "Base case vs bear case; catalyst and headwind framing. YOLO moon",
    )
    assert r.quality_score > 0
    assert r.noise_score < 0.9


@pytest.mark.asyncio
async def test_pipeline_digest(monkeypatch):
    monkeypatch.setenv("BOT_MODE", "demo")
    from config import reload_config

    reload_config()
    pipe = IdeaPipeline()
    assert pipe.settings.is_demo
    ideas = await pipe.digest(limit=10)
    assert len(ideas) >= 3
    # CXMT / research piece should outrank pure WSB
    titles = [i.item.title for i in ideas]
    assert any("CXMT" in t or "HBM" in t or "Kimi" in t for t in titles)
    wsb = next((i for i in ideas if "YOLO" in i.item.title or "moon" in i.item.title.lower()), None)
    top = ideas[0]
    if wsb:
        assert top.score >= wsb.score
    reload_config()


@pytest.mark.asyncio
async def test_theme_filter():
    pipe = IdeaPipeline()
    ideas = await pipe.digest(theme_id="memory_semiconductors", limit=10)
    assert ideas
    assert all(
        any(h.theme_id == "memory_semiconductors" for h in i.theme_hits) for i in ideas
    )


def test_fixtures_load():
    items = load_fixtures()
    assert len(items) >= 5
