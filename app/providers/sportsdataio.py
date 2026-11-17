"""SportsDataIO REST client.

Auth header: Ocp-Apim-Subscription-Key.
Soccer is v4 (https://api.sportsdata.io/v4/soccer/...); US leagues are v3
(https://api.sportsdata.io/v3/{nba|nfl|mlb|nhl}/...).
Free trial soccer = UEFA Champions League (competition 3) only.
Cricket is listed on the coverage page but not in the public OpenAPI files -
ask the vendor for the cricket/Global API paths, then call them via `get()`.
"""

from datetime import date
from typing import Any

import httpx

from app.providers.base import BaseHTTPProvider
from app.services.latency import LatencyTracker


def _d(day: date | str) -> str:
    return day.isoformat() if isinstance(day, date) else day


class SportsDataIOClient(BaseHTTPProvider):
    name = "sportsdataio"

    def __init__(self, client: httpx.AsyncClient, tracker: LatencyTracker, api_key: str,
                 base_url: str = "https://api.sportsdata.io"):
        super().__init__(client, tracker, api_key)
        self.base = base_url.rstrip("/")

    def _auth_headers(self) -> dict[str, str]:
        return {"Ocp-Apim-Subscription-Key": self.api_key}

    async def get(self, path: str, params: dict[str, Any] | None = None, kind: str | None = None) -> Any:
        path = path.lstrip("/")
        # kind groups latency by product, e.g. "rest:v4/soccer"
        product = "/".join(path.split("/")[:2])
        return await self._get(f"{self.base}/{path}", params, kind=kind or f"rest:{product}")

    # --- soccer (v4) ----------------------------------------------------
    async def soccer_competitions(self) -> Any:
        return await self.get("v4/soccer/scores/json/Competitions")

    async def soccer_games_by_date(self, competition: str, day: date | str) -> Any:
        return await self.get(f"v4/soccer/scores/json/GamesByDate/{competition}/{_d(day)}")

    async def soccer_box_scores_by_date(self, competition: str, day: date | str) -> Any:
        return await self.get(f"v4/soccer/stats/json/BoxScoresByDate/{competition}/{_d(day)}")

    async def soccer_box_score(self, competition: str, game_id: int | str) -> Any:
        return await self.get(f"v4/soccer/stats/json/BoxScore/{competition}/{game_id}")

    async def soccer_injuries(self, competition: str) -> Any:
        return await self.get(f"v4/soccer/projections/json/InjuredPlayers/{competition}")

    async def soccer_lineups_by_date(self, competition: str, day: date | str) -> Any:
        return await self.get(f"v4/soccer/stats/json/LineupsByDate/{competition}/{_d(day)}")

    async def soccer_teams(self, competition: str) -> Any:
        return await self.get(f"v4/soccer/scores/json/Teams/{competition}")

    # --- US leagues (v3) ------------------------------------------------
    async def games_by_date(self, league: str, day: date | str) -> Any:
        """league: nba | mlb | nhl (NFL uses weeks - use get('v3/nfl/scores/json/ScoresByWeek/...'))."""
        return await self.get(f"v3/{league}/scores/json/GamesByDate/{_d(day)}")

    async def injuries(self, league: str) -> Any:
        return await self.get(f"v3/{league}/projections/json/InjuredPlayers")
