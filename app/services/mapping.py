"""Map fixtures to exchange contracts and across vendors.

1. Exchanges: OddsPapi already links its fixtures to Kalshi/Polymarket/etc.
   `/fixtures/odds?bookmakers=...` tells us which exchanges price the match,
   `/fixtures/mapping?bookmaker=...` gives the exchange's own fixture id.
2. SportsDataIO <-> OddsPapi: fuzzy match on team names + kickoff time
   (until SDX IDs are available for both sides).
"""

import logging
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from app.providers.base import ProviderError
from app.providers.oddspapi import OddsPapiClient
from app.services.normalize import as_list

log = logging.getLogger(__name__)

_STOPWORDS = {"fc", "cf", "sc", "afc", "the", "club", "de", "cd", "ac"}


def norm_team(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    return " ".join(t for t in tokens if t not in _STOPWORDS)


def name_similarity(a: str, b: str) -> float:
    a, b = norm_team(a), norm_team(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match_score(home_a: str, away_a: str, start_a: datetime,
                home_b: str, away_b: str, start_b: datetime,
                max_time_diff: timedelta = timedelta(hours=2)) -> float:
    """0..1 confidence that two fixtures are the same match."""
    if abs(start_a - start_b) > max_time_diff:
        return 0.0
    straight = (name_similarity(home_a, home_b) + name_similarity(away_a, away_b)) / 2
    swapped = (name_similarity(home_a, away_b) + name_similarity(away_a, home_b)) / 2 * 0.95
    time_factor = 1 - (abs(start_a - start_b) / max_time_diff) * 0.2
    return round(max(straight, swapped) * time_factor, 3)


def best_match(target: dict, candidates: list[dict], threshold: float = 0.8) -> tuple[dict | None, float]:
    best, best_score = None, 0.0
    for c in candidates:
        s = match_score(target["home"], target["away"], target["start_time"],
                        c["home"], c["away"], c["start_time"])
        if s > best_score:
            best, best_score = c, s
    return (best, best_score) if best_score >= threshold else (None, best_score)


def _exchange_fixture_id(mapping_resp: Any, fixture_id: str) -> str | None:
    for row in as_list(mapping_resp):
        if str(row.get("fixtureId", fixture_id)) != fixture_id:
            continue
        for key in ("bookmakerFixtureId", "bookmakerEventId", "externalId", "slug", "ticker"):
            if row.get(key):
                return str(row[key])
    if isinstance(mapping_resp, dict) and isinstance(mapping_resp.get(fixture_id), (str, int)):
        return str(mapping_resp[fixture_id])
    return None


async def discover_exchange_markets(client: OddsPapiClient, fixture_id: str,
                                    exchanges: list[str]) -> dict[str, dict]:
    """Return {exchange: {"market_count", "exchange_fixture_id", "raw"}} for exchanges listing this fixture."""
    odds = await client.fixture_odds(fixture_id, bookmakers=exchanges)
    books: dict = {}
    if isinstance(odds, dict):
        books = odds.get("odds") or odds.get("bookmakerOdds") or {}
    found: dict[str, dict] = {}
    for exchange, entries in (books or {}).items():
        if exchange not in exchanges or not entries:
            continue
        count = len(entries) if hasattr(entries, "__len__") else 1
        found[exchange] = {"market_count": count, "exchange_fixture_id": None, "raw": None}

    for exchange in found:
        try:
            mapping = await client.fixtures_mapping(exchange, [fixture_id])
            found[exchange]["exchange_fixture_id"] = _exchange_fixture_id(mapping, fixture_id)
            found[exchange]["raw"] = mapping if isinstance(mapping, (dict, list)) else None
        except ProviderError as exc:
            log.warning("mapping lookup failed for %s/%s: %s", exchange, fixture_id, exc)
    return found
