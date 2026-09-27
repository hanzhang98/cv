from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import DiscoveryConfig
from .models import PoolSnapshot, TokenRisk


class PublicAPIError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class GeckoTerminalClient:
    base_url = "https://api.geckoterminal.com/api/v2"

    def __init__(self, config: DiscoveryConfig):
        self.config = config
        self._last_request_at = 0.0

    def _get(self, path: str, parameters: dict[str, Any]) -> dict[str, Any]:
        wait = self.config.request_interval_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        url = f"{self.base_url}{path}?{urlencode(parameters)}"
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": self.config.user_agent},
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PublicAPIError(f"GeckoTerminal request failed for {path}: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()
        return payload

    def discover(self, observed_at: datetime) -> list[PoolSnapshot]:
        snapshots: list[PoolSnapshot] = []
        for source in self.config.sources:
            if source not in {"pools", "trending_pools", "new_pools"}:
                raise ValueError(f"unsupported GeckoTerminal source: {source}")
            for page in range(1, self.config.pages_per_source + 1):
                payload = self._get(
                    f"/networks/{self.config.network}/{source}",
                    {"page": page, "include": "base_token,quote_token"},
                )
                snapshots.extend(
                    self._parse_payload(payload, observed_at, discovery_source=source)
                )
        return snapshots

    def get_pool(self, pool_address: str, observed_at: datetime) -> PoolSnapshot | None:
        payload = self._get(
            f"/networks/{self.config.network}/pools/{pool_address}",
            {"include": "base_token,quote_token"},
        )
        rows = self._parse_payload(payload, observed_at, discovery_source="paper_refresh")
        return rows[0] if rows else None

    def _parse_payload(
        self,
        payload: dict[str, Any],
        observed_at: datetime,
        discovery_source: str,
    ) -> list[PoolSnapshot]:
        raw_data = payload.get("data", [])
        data = raw_data if isinstance(raw_data, list) else [raw_data]
        included = {
            item["id"]: item.get("attributes", {})
            for item in payload.get("included", [])
            if item.get("type") == "token" and "id" in item
        }
        parsed: list[PoolSnapshot] = []
        for item in data:
            attributes = item.get("attributes", {})
            relationships = item.get("relationships", {})
            base_id = relationships.get("base_token", {}).get("data", {}).get("id", "")
            quote_id = relationships.get("quote_token", {}).get("data", {}).get("id", "")
            base = included.get(base_id, {})
            token_address = base.get("address") or base_id.removeprefix(
                f"{self.config.network}_"
            )
            quote_address = included.get(quote_id, {}).get("address") or quote_id.removeprefix(
                f"{self.config.network}_"
            )
            pool_address = attributes.get("address")
            if not token_address or not pool_address:
                continue
            transactions = attributes.get("transactions", {}).get("h24", {})
            parsed.append(
                PoolSnapshot(
                    network=self.config.network,
                    pool_address=pool_address,
                    token_address=token_address,
                    token_symbol=base.get("symbol") or attributes.get("name", "").split(" / ")[0],
                    token_name=base.get("name") or "",
                    quote_token_address=quote_address,
                    dex_id=relationships.get("dex", {}).get("data", {}).get("id", ""),
                    observed_at=observed_at,
                    pool_created_at=_timestamp(attributes.get("pool_created_at")),
                    price_usd=_number(attributes.get("base_token_price_usd")),
                    liquidity_usd=_number(attributes.get("reserve_in_usd")),
                    volume_24h_usd=_number(attributes.get("volume_usd", {}).get("h24")),
                    market_cap_usd=_number(attributes.get("market_cap_usd")),
                    fdv_usd=_number(attributes.get("fdv_usd")),
                    price_change_24h_pct=_number(
                        attributes.get("price_change_percentage", {}).get("h24")
                    ),
                    buys_24h=_integer(transactions.get("buys")),
                    sells_24h=_integer(transactions.get("sells")),
                    discovery_sources=(discovery_source,),
                )
            )
        return parsed


class SolanaClient:
    def __init__(
        self,
        endpoint: str = "https://api.mainnet-beta.solana.com",
        user_agent: str = "meme-scanner/0.1 (forward research journal)",
    ):
        self.endpoint = endpoint
        self.user_agent = user_agent
        self._request_id = 0

    def _call(self, method: str, parameters: Iterable[Any]) -> dict[str, Any]:
        self._request_id += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": list(parameters),
            }
        ).encode()
        request = Request(
            self.endpoint,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        if payload.get("error"):
            raise PublicAPIError(f"Solana {method} failed: {payload['error']}")
        return payload["result"]

    def token_risk(self, token_address: str) -> TokenRisk:
        try:
            account = self._call(
                "getAccountInfo",
                [token_address, {"encoding": "jsonParsed", "commitment": "finalized"}],
            )
            value = account.get("value")
            if not value:
                raise PublicAPIError("mint account was not found")
            info = value["data"]["parsed"]["info"]
            supply = float(info["supply"])
            largest = self._call(
                "getTokenLargestAccounts",
                [token_address, {"commitment": "finalized"}],
            ).get("value", [])
            concentrations = [
                (float(item["amount"]) / supply * 100) for item in largest if supply > 0
            ]
            return TokenRisk(
                mint_authority_revoked=info.get("mintAuthority") is None,
                freeze_authority_revoked=info.get("freezeAuthority") is None,
                raw_largest_account_pct=max(concentrations, default=None),
                raw_top20_accounts_pct=sum(concentrations) if concentrations else None,
            )
        except (KeyError, TypeError, ValueError, HTTPError, URLError, TimeoutError, PublicAPIError) as exc:
            return TokenRisk(None, None, None, None, error=str(exc))
