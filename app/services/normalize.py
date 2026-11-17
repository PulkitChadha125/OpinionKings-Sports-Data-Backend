"""Convert vendor payloads into our canonical shape.

Vendor response envelopes aren't fully documented yet, so these helpers are
defensive: they accept lists, {"data": [...]}, or dicts keyed by id.
Run scripts/test_apis.py and inspect samples/ to tighten them up.
"""

from datetime import datetime, timezone
from typing import Any


def as_list(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for key in ("data", "fixtures", "items", "results"):
            if isinstance(data.get(key), list):
                return [d for d in data[key] if isinstance(d, dict)]
        values = list(data.values())
        if values and all(isinstance(v, dict) for v in values):
            return values
        return [data]
    return []


def epoch_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            if not value.isdigit():
                return None
            value = int(value)
    value = float(value)
    if value > 1e12:  # milliseconds
        value /= 1000
    return datetime.fromtimestamp(value, tz=timezone.utc)


def extract_result_score(scores: Any) -> tuple[int | None, int | None]:
    """OddsPapi scores are keyed by period; the `result` period is authoritative."""
    if not isinstance(scores, dict):
        return None, None
    candidates = [scores.get("result"), scores.get("periods", {}).get("result") if isinstance(scores.get("periods"), dict) else None]
    if "participant1Score" in scores:
        candidates.append(scores)
    for c in candidates:
        if isinstance(c, dict) and "participant1Score" in c:
            return c.get("participant1Score"), c.get("participant2Score")
    return None, None


def parse_oddspapi_fixture(raw: dict) -> dict | None:
    fixture_id = raw.get("fixtureId") or raw.get("id")
    start = epoch_to_dt(raw.get("startTime"))
    if not fixture_id or start is None:
        return None
    home_score, away_score = extract_result_score(raw.get("scores"))
    return {
        "oddspapi_id": str(fixture_id),
        "sport_id": raw.get("sportId"),
        "sport_name": raw.get("sportName"),
        "tournament_id": raw.get("tournamentId"),
        "tournament_name": raw.get("tournamentName"),
        "home": raw.get("participant1Name") or "TBD",
        "away": raw.get("participant2Name") or "TBD",
        "start_time": start,
        "vendor_status_id": raw.get("statusId"),
        "scores": raw.get("scores"),
        "home_score": home_score,
        "away_score": away_score,
    }


def parse_sportsdataio_soccer_game(raw: dict) -> dict | None:
    game_id = raw.get("GameId")
    start = epoch_to_dt(raw.get("DateTime") or raw.get("Day"))
    if game_id is None or start is None:
        return None
    return {
        "sportsdataio_id": str(game_id),
        "home": raw.get("HomeTeamName") or raw.get("HomeTeamKey") or "",
        "away": raw.get("AwayTeamName") or raw.get("AwayTeamKey") or "",
        "start_time": start,
        "status": raw.get("Status"),
        "home_score": raw.get("HomeTeamScore"),
        "away_score": raw.get("AwayTeamScore"),
    }
