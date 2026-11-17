"""OddsPapi v5 REST client.

Docs: https://docs.oddspapi.io  (base https://v5.oddspapi.io/{lang}, header X-API-Key)
Rate limits: 10 req/s on odds endpoints, 200 req/min elsewhere.
"""

from typing import Any

import httpx

from app.providers.base import BaseHTTPProvider
from app.services.latency import LatencyTracker

# OddsPapi fixture statusId
STATUS_PREGAME = 0
STATUS_LIVE = 1
STATUS_FINISHED = 2
STATUS_CANCELLED = 3
STATUS_REMOVED = 4


def _join(values: list[str] | list[int] | str | None) -> str | None:
    if values is None:
        return None
    if isinstance(values, str):
        return values
    return ",".join(str(v) for v in values)


class OddsPapiClient(BaseHTTPProvider):
    name = "oddspapi"

    def __init__(self, client: httpx.AsyncClient, tracker: LatencyTracker, api_key: str,
                 base_url: str = "https://v5.oddspapi.io", lang: str = "en"):
        super().__init__(client, tracker, api_key)
        self.base = f"{base_url.rstrip('/')}/{lang}"

    def _auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    async def get(self, path: str, params: dict[str, Any] | None = None, kind: str | None = None) -> Any:
        path = path.lstrip("/")
        return await self._get(f"{self.base}/{path}", params, kind=kind or f"rest:{path}")

    # --- reference data -------------------------------------------------
    async def sports(self) -> Any:
        return await self.get("sports")

    async def bookmakers(self, bookmakers: list[str] | None = None) -> Any:
        return await self.get("bookmakers", {"bookmakers": _join(bookmakers)})

    async def tournaments(self, sport_id: int) -> Any:
        return await self.get("tournaments", {"sportId": sport_id})

    async def markets(self, sport_id: int) -> Any:
        return await self.get("markets", {"sportId": sport_id})

    # --- fixtures -------------------------------------------------------
    async def fixtures(self, sport_id: int | None = None, tournament_id: int | None = None,
                       status_id: int | None = None, bookmakers: list[str] | None = None,
                       **extra: Any) -> Any:
        params = {"sportId": sport_id, "tournamentId": tournament_id, "statusId": status_id,
                  "bookmakers": _join(bookmakers), **extra}
        return await self.get("fixtures", params)

    async def fixtures_by_ids(self, fixture_ids: list[str]) -> Any:
        return await self.get("fixtures", {"fixtureIds": _join(fixture_ids)})

    async def fixtures_live(self, sport_id: int | None = None, bookmakers: list[str] | None = None) -> Any:
        return await self.get("fixtures/live", {"sportId": sport_id, "bookmakers": _join(bookmakers)})

    async def fixtures_today(self, sport_id: int | None = None, bookmakers: list[str] | None = None) -> Any:
        return await self.get("fixtures/today", {"sportId": sport_id, "bookmakers": _join(bookmakers)})

    # --- odds / mapping / settlement ------------------------------------
    async def fixture_odds(self, fixture_id: str, bookmakers: list[str] | None = None) -> Any:
        return await self.get("fixtures/odds", {"fixtureId": fixture_id, "bookmakers": _join(bookmakers)},
                              kind="rest:fixtures/odds")

    async def fixtures_mapping(self, bookmaker: str, fixture_ids: list[str]) -> Any:
        return await self.get("fixtures/mapping", {"bookmaker": bookmaker, "fixtureIds": _join(fixture_ids)})

    async def settlement(self, fixture_id: str) -> Any:
        return await self.get("fixtures/settlement", {"fixtureId": fixture_id})
