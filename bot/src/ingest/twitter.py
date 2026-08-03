from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from models.ideas import RawItem, SourceType


def _tweet_id(handle: str, text: str, created: str) -> str:
    return hashlib.sha1(f"{handle}|{created}|{text[:80]}".encode()).hexdigest()[:16]


class TwitterIngester:
    """Twitter/X ingest.

    Live path uses Twitter API v2 recent search when TWITTER_BEARER_TOKEN is set.
    Without a token, callers should load fixtures instead (see pipeline).
    """

    SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"

    def __init__(
        self,
        bearer_token: str,
        accounts: list[dict],
        queries: list[str],
        timeout: float = 20.0,
    ) -> None:
        self.bearer_token = bearer_token
        self.accounts = accounts
        self.queries = queries
        self.timeout = timeout
        self._account_meta = {
            a["handle"].lstrip("@").lower(): a for a in accounts if a.get("handle")
        }

    @property
    def enabled(self) -> bool:
        return bool(self.bearer_token.strip())

    async def fetch_all(self, client: httpx.AsyncClient | None = None) -> list[RawItem]:
        if not self.enabled:
            return []
        owns = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout)
        items: list[RawItem] = []
        try:
            for q in self._build_queries():
                items.extend(await self._search(client, q))
        finally:
            if owns:
                await client.aclose()
        return items

    def _build_queries(self) -> list[str]:
        queries = list(self.queries)
        # Also pull from curated handles (OR batches of ~8)
        handles = [a["handle"].lstrip("@") for a in self.accounts if a.get("handle")]
        for i in range(0, len(handles), 8):
            batch = handles[i : i + 8]
            from_q = " OR ".join(f"from:{h}" for h in batch)
            queries.append(f"({from_q}) -is:retweet lang:en")
        return queries

    async def _search(self, client: httpx.AsyncClient, query: str) -> list[RawItem]:
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        params = {
            "query": query,
            "max_results": 25,
            "tweet.fields": "created_at,author_id,lang,public_metrics,entities",
            "expansions": "author_id",
            "user.fields": "username,name",
        }
        try:
            resp = await client.get(self.SEARCH_URL, headers=headers, params=params)
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            payload = resp.json()
        except Exception:  # noqa: BLE001
            return []

        users = {
            u["id"]: u for u in (payload.get("includes") or {}).get("users") or []
        }
        out: list[RawItem] = []
        for tw in payload.get("data") or []:
            text = (tw.get("text") or "").strip()
            if not text:
                continue
            author = users.get(tw.get("author_id") or "", {})
            handle = (author.get("username") or "unknown").lstrip("@")
            meta = self._account_meta.get(handle.lower(), {})
            created = tw.get("created_at")
            published = None
            if created:
                try:
                    published = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    published = None
            url = f"https://x.com/{handle}/status/{tw.get('id')}"
            title = text.split("\n", 1)[0][:180]
            out.append(
                RawItem(
                    id=_tweet_id(handle, text, created or ""),
                    source_type=SourceType.TWITTER,
                    source_name=f"@{handle}",
                    title=title,
                    summary=text[:1200],
                    url=url,
                    author=handle,
                    published_at=published or datetime.now(timezone.utc),
                    source_weight=float(meta.get("weight", 0.7)),
                    noise_bias=float(meta.get("noise_bias", 0.0)),
                    tags=list(meta.get("tags") or []),
                    raw={"query": query},
                )
            )
        return out
