"""Write docs/api_endpoints.csv: every endpoint, its parameters, and a real example response.

Usage:  python -m scripts.export_endpoints_csv
Calls each endpoint in-process against the live vendor APIs (needs keys in .env).
Slow or DB-changing admin jobs are listed but not executed.
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

OUT = ROOT / "docs" / "api_endpoints.csv"
MAX_RESPONSE_CHARS = 6000
SKIP = {
    ("POST", "/admin/activate-markets"): "Not executed: slow (about 1 s per fixture starting within 24 h).",
    ("POST", "/admin/link-sportsdataio"): "Not executed: needs SPORTSDATAIO_API_KEY.",
}


def describe_param(p: dict, spec: dict) -> str:
    schema = p.get("schema", {})
    if "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].split("/")[-1]]
    if "anyOf" in schema:
        schema = next((s for s in schema["anyOf"] if s.get("type") != "null"), schema)
    bits = [p["in"], "required" if p.get("required") else "optional", schema.get("type", "string")]
    if "default" in schema:
        bits.append(f"default={schema['default']}")
    if "enum" in schema:
        bits.append("one of: " + "/".join(map(str, schema["enum"])))
    text = f"{p['name']} ({', '.join(bits)})"
    if p.get("description"):
        text += f" - {p['description']}"
    return text


def summarize_fields(data: Any) -> str:
    if isinstance(data, list):
        first = data[0] if data else None
        keys = ", ".join(first.keys()) if isinstance(first, dict) else ""
        return f"array of {len(data)} items" + (f"; item fields: {keys}" if keys else "")
    if isinstance(data, dict):
        return "object; fields: " + ", ".join(data.keys())
    return type(data).__name__


def main() -> None:
    spec = app.openapi()
    with TestClient(app) as client:
        # Pick a real upcoming Kalshi fixture so the fixture-specific examples return data.
        fixtures = client.get("/exchanges/kalshi/fixtures", params={"sport_id": 10, "status": "upcoming"}).json()
        fid = fixtures[0]["oddspapi_id"] if isinstance(fixtures, list) and fixtures else "id1000085176169220"
        today = date.today().isoformat()

        # (method, path) -> list of (path_values, query_params) examples to run
        examples: dict[tuple[str, str], list[tuple[dict, dict]]] = {
            ("GET", "/metrics/latency/history"): [({}, {"provider": "oddspapi", "limit": 5})],
            ("GET", "/exchanges/{exchange}/fixtures"): [
                ({"exchange": "kalshi"}, {"sport_id": 10, "status": "upcoming"}),
                ({"exchange": "polymarket"}, {"sport_id": 11, "status": "live"}),
                ({"exchange": "kalshi"}, {"sport_id": 10, "status": "upcoming", "raw": "true"}),
            ],
            ("GET", "/exchanges/{exchange}/fixtures/{fixture_id}/odds"): [({"exchange": "kalshi", "fixture_id": fid}, {})],
            ("GET", "/exchanges/{exchange}/mapping"): [({"exchange": "kalshi"}, {"fixture_ids": fid})],
            ("GET", "/stats/soccer/games"): [({}, {"competition": 3, "day": today})],
            ("GET", "/stats/soccer/box-scores"): [({}, {"competition": 3, "day": today})],
            ("GET", "/stats/soccer/box-score/{game_id}"): [({"game_id": "12345"}, {})],
            ("GET", "/stats/soccer/lineups"): [({}, {"competition": 3, "day": today})],
            ("GET", "/stats/{league}/games"): [({"league": "nba"}, {"day": today})],
            ("GET", "/stats/{league}/injuries"): [({"league": "nba"}, {})],
            ("GET", "/fixtures"): [({}, {"sport_id": 10, "limit": 3})],
            ("GET", "/fixtures/{fixture_id}"): [({"fixture_id": fid}, {})],
            ("GET", "/vendors/oddspapi/{path}"): [({"path": "fixtures/today"}, {"sportId": 10})],
            ("GET", "/vendors/sportsdataio/{path}"): [({"path": "v4/soccer/scores/json/Competitions"}, {})],
        }

        rows = []
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                method = method.upper()
                params = "; ".join(describe_param(p, spec) for p in op.get("parameters", [])) or "none"
                base = {
                    "Group": ", ".join(op.get("tags", [])),
                    "Method": method,
                    "Endpoint": path,
                    "Description": (op.get("summary") or "") + (f" - {op['description'].strip()}" if op.get("description") else ""),
                    "Parameters": params,
                }
                if (method, path) in SKIP:
                    rows.append({**base, "Example request": f"curl -X {method} \"http://localhost:8000{path}\"",
                                 "HTTP status": "", "Response fields": "", "Example response": SKIP[(method, path)]})
                    continue
                for path_vals, query in examples.get((method, path), [({}, {})]):
                    url = path.format(**path_vals)
                    resp = client.request(method, url, params=query)
                    qs = "&".join(f"{k}={v}" for k, v in query.items())
                    full = f"http://localhost:8000{url}" + (f"?{qs}" if qs else "")
                    curl = f"curl -X {method} \"{full}\"" if method != "GET" else f"curl \"{full}\""
                    try:
                        data = resp.json()
                        fields = summarize_fields(data)
                        body = json.dumps(data, default=str)
                    except ValueError:
                        fields, body = "text", resp.text
                    if len(body) > MAX_RESPONSE_CHARS:
                        body = body[:MAX_RESPONSE_CHARS] + f"\n... (truncated, {len(body)} chars total)"
                    rows.append({**base, "Example request": curl, "HTTP status": resp.status_code,
                                 "Response fields": fields, "Example response": body})
                    print(f"{resp.status_code} {method} {full}")

    rows.append({
        "Group": "live", "Method": "WEBSOCKET", "Endpoint": "/ws/live",
        "Description": "Live stream for the frontend (scores, fixtures, odds, lifecycle, heartbeat). "
                       "Needs BACKGROUND_JOBS_ENABLED=true so the OddsPapi stream feeds it.",
        "Parameters": "fixture_id (query, optional, string) - only this match; omit for everything",
        "Example request": "ws://localhost:8000/ws/live?fixture_id=" + fid,
        "HTTP status": "101", "Response fields": "object; fields: type, fixtureId, ts, payload",
        "Example response": '{"type": "odds", "fixtureId": "' + fid + '", "ts": 1794927229749, "payload": {...}}',
    })

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig so Excel opens it cleanly
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
