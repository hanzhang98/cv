from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
from bs4 import BeautifulSoup

from models.ideas import RawItem, SourceType


def _parse_dt(entry: dict[str, Any]) -> datetime | None:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
    parsed = entry.get("published_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    return None


def _entry_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode()).hexdigest()[:16]


def _plain(html_or_text: str) -> str:
    if not html_or_text:
        return ""
    if "<" not in html_or_text:
        return html_or_text.strip()
    return BeautifulSoup(html_or_text, "lxml").get_text(" ", strip=True)


class SubstackIngester:
    def __init__(self, feeds: list[dict], timeout: float = 20.0) -> None:
        self.feeds = feeds
        self.timeout = timeout

    async def fetch_all(self, client: httpx.AsyncClient | None = None) -> list[RawItem]:
        owns = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        items: list[RawItem] = []
        try:
            for feed in self.feeds:
                items.extend(await self._fetch_one(client, feed))
        finally:
            if owns:
                await client.aclose()
        return items

    async def _fetch_one(self, client: httpx.AsyncClient, feed: dict) -> list[RawItem]:
        url = feed["url"]
        name = feed.get("name") or url
        weight = float(feed.get("weight", 1.0))
        tags = list(feed.get("tags") or [])
        try:
            resp = await client.get(
                url,
                headers={
                    # Browser-like UA: many newsletter hosts block generic bots / DC IPs.
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; InvestmentIdeasBot/0.2; "
                        "+https://github.com/hanzhang98/cv)"
                    ),
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
            )
            resp.raise_for_status()
            parsed = feedparser.parse(resp.text)
        except Exception:  # noqa: BLE001 — soft-fail per feed
            return []

        out: list[RawItem] = []
        for entry in parsed.entries[:20]:
            link = entry.get("link") or ""
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            summary = _plain(entry.get("summary") or entry.get("description") or "")[:1200]
            author = entry.get("author")
            out.append(
                RawItem(
                    id=_entry_id(link or title, title),
                    source_type=SourceType.SUBSTACK,
                    source_name=name,
                    title=title,
                    summary=summary,
                    url=link or url,
                    author=author,
                    published_at=_parse_dt(entry),
                    source_weight=weight,
                    tags=tags,
                )
            )
        return out
