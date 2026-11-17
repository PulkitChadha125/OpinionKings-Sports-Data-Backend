"""Smoke-test every vendor endpoint we depend on and write a report.

Usage:  python -m scripts.test_apis [--ws-seconds 30] [--skip-ws]
Output: console table, samples/<vendor>__<check>.json, reports/api_test_<timestamp>.md
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.providers.base import MissingCredentials, ProviderError  # noqa: E402
from app.providers.oddspapi import OddsPapiClient  # noqa: E402
from app.providers.sportsdataio import SportsDataIOClient  # noqa: E402
from app.services.latency import LatencyTracker  # noqa: E402
from app.services.live_hub import LiveHub  # noqa: E402
from app.services.normalize import as_list, parse_oddspapi_fixture  # noqa: E402
from app.services.oddspapi_ws import OddsPapiStream  # noqa: E402

SAMPLES = ROOT / "samples"
REPORTS = ROOT / "reports"
results: list[dict] = []


def _shape(data: Any) -> tuple[int | None, str]:
    items = as_list(data)
    keys = sorted(items[0].keys())[:12] if items else (sorted(data.keys())[:12] if isinstance(data, dict) else [])
    return len(items), ", ".join(keys)


async def check(vendor: str, name: str, fn: Callable[[], Awaitable[Any]]) -> Any:
    started = time.perf_counter()
    row = {"vendor": vendor, "check": name}
    try:
        data = await fn()
        row.update(ok=True, ms=round((time.perf_counter() - started) * 1000), detail="")
        row["items"], row["keys"] = _shape(data)
        SAMPLES.mkdir(exist_ok=True)
        (SAMPLES / f"{vendor}__{name}.json").write_text(json.dumps(data, indent=2, default=str)[:2_000_000])
    except MissingCredentials:
        data = None
        row.update(ok=None, ms=None, items=None, keys="", detail="SKIPPED - no API key in .env")
    except ProviderError as exc:
        data = None
        row.update(ok=False, ms=round((time.perf_counter() - started) * 1000), items=None, keys="",
                   detail=f"HTTP {exc.status}: {exc.message[:160]}")
    status = {True: "PASS", False: "FAIL", None: "SKIP"}[row["ok"]]
    print(f"[{status}] {vendor:12} {name:32} {str(row['ms'] or '-'):>6} ms  items={row['items']}  {row['detail']}")
    results.append(row)
    return data


def find_sport_id(sports: Any, name: str) -> int | None:
    for s in as_list(sports):
        if name.lower() in str(s.get("sportName") or s.get("name") or s.get("slug") or "").lower():
            return s.get("sportId") or s.get("id")
    return None


async def test_oddspapi(op: OddsPapiClient, exchanges: list[str]) -> dict:
    ctx: dict = {}
    sports = await check("oddspapi", "sports", op.sports)
    ctx["cricket_id"] = find_sport_id(sports, "cricket")
    if sports is not None:
        print(f"         -> cricket sportId = {ctx['cricket_id']}")
    await check("oddspapi", "bookmakers_exchanges", lambda: op.bookmakers(exchanges))
    await check("oddspapi", "tournaments_soccer", lambda: op.tournaments(10))
    if ctx["cricket_id"]:
        await check("oddspapi", "tournaments_cricket", lambda: op.tournaments(ctx["cricket_id"]))

    fixtures_all: list[dict] = []
    for label, sid in (("soccer", 10), ("basketball", 11), ("cricket", ctx["cricket_id"])):
        if sid is None:
            continue
        data = await check("oddspapi", f"fixtures_{label}_on_exchanges",
                           lambda sid=sid: op.fixtures(sport_id=sid, bookmakers=exchanges))
        fixtures_all += [f for f in (parse_oddspapi_fixture(r) for r in as_list(data)) if f]
    await check("oddspapi", "fixtures_live", lambda: op.fixtures_live(bookmakers=exchanges))
    await check("oddspapi", "fixtures_today", lambda: op.fixtures_today(bookmakers=exchanges))

    now = datetime.now(timezone.utc)
    upcoming = sorted((f for f in fixtures_all if f["start_time"] >= now - timedelta(hours=3)),
                      key=lambda f: f["start_time"])
    if not upcoming:
        print("         -> no upcoming fixtures on exchanges; skipping odds/mapping checks")
        return ctx
    fx = upcoming[0]
    ctx["sample_fixture"] = fx
    print(f"         -> sample fixture {fx['oddspapi_id']}: {fx['home']} vs {fx['away']} @ {fx['start_time']}")
    odds = await check("oddspapi", "fixture_odds_exchanges", lambda: op.fixture_odds(fx["oddspapi_id"], exchanges))
    listed = list((odds or {}).get("odds", {}).keys()) if isinstance(odds, dict) else []
    print(f"         -> exchanges pricing this fixture: {listed or 'none'}")
    for ex in (listed or exchanges)[:3]:
        await check("oddspapi", f"mapping_{ex}", lambda ex=ex: op.fixtures_mapping(ex, [fx["oddspapi_id"]]))
    finished = [f for f in fixtures_all if f["vendor_status_id"] == 2]
    if finished:
        await check("oddspapi", "settlement_finished_fixture", lambda: op.settlement(finished[0]["oddspapi_id"]))
    return ctx


async def test_oddspapi_ws(settings, seconds: int) -> None:
    if not settings.oddspapi_api_key:
        results.append({"vendor": "oddspapi", "check": "websocket", "ok": None, "ms": None, "items": None,
                        "keys": "", "detail": "SKIPPED - no API key in .env"})
        print("[SKIP] oddspapi     websocket")
        return
    tracker = LatencyTracker()
    stream = OddsPapiStream(settings.oddspapi_ws_url, settings.oddspapi_api_key, settings.ws_channel_list,
                            tracker, LiveHub())
    print(f"         -> listening to WebSocket for {seconds}s on {settings.ws_channel_list} ...")
    await stream.run(stop_after=seconds)
    total = sum(stream.message_counts.values())
    ok = stream.last_login_ok is not None and stream.last_error is None
    lat = {s["kind"]: f"p50={s['p50_ms']}ms p95={s['p95_ms']}ms" for s in tracker.stats() if s["samples"]}
    detail = f"login_ok={stream.last_login_ok is not None} msgs={stream.message_counts} delay={lat}"
    if stream.last_error:
        detail += f" error={stream.last_error[:200]}"
    results.append({"vendor": "oddspapi", "check": "websocket", "ok": ok, "ms": None, "items": total,
                    "keys": "", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] oddspapi     websocket  {detail}")


async def test_sportsdataio(sd: SportsDataIOClient, competition: str) -> None:
    today = date.today()
    await check("sportsdataio", "soccer_competitions", sd.soccer_competitions)
    await check("sportsdataio", "soccer_teams", lambda: sd.soccer_teams(competition))
    for offset in (0, 1):
        d = today + timedelta(days=offset)
        await check("sportsdataio", f"soccer_games_{d}", lambda d=d: sd.soccer_games_by_date(competition, d))
    await check("sportsdataio", "soccer_box_scores_today", lambda: sd.soccer_box_scores_by_date(competition, today))
    await check("sportsdataio", "soccer_lineups_today", lambda: sd.soccer_lineups_by_date(competition, today))
    await check("sportsdataio", "soccer_injuries", lambda: sd.soccer_injuries(competition))
    for league in ("nba", "nhl"):
        await check("sportsdataio", f"{league}_games_today", lambda lg=league: sd.games_by_date(lg, today))
    await check("sportsdataio", "nba_injuries", lambda: sd.injuries("nba"))


def write_report() -> Path:
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"api_test_{datetime.now():%Y%m%d_%H%M%S}.md"
    lines = ["# Vendor API test report", f"_Run at {datetime.now():%Y-%m-%d %H:%M}_", "",
             "| Vendor | Check | Result | Latency ms | Items | Keys / detail |", "|---|---|---|---|---|---|"]
    for r in results:
        status = {True: "PASS", False: "FAIL", None: "SKIP"}[r["ok"]]
        info = (r["detail"] or r["keys"]).replace("|", "/")
        lines.append(f"| {r['vendor']} | {r['check']} | {status} | {r['ms'] or ''} | {r['items'] or ''} | {info} |")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ws-seconds", type=int, default=30)
    parser.add_argument("--skip-ws", action="store_true")
    args = parser.parse_args()

    s = get_settings()
    tracker = LatencyTracker()
    async with httpx.AsyncClient() as http:
        op = OddsPapiClient(http, tracker, s.oddspapi_api_key, s.oddspapi_base_url, s.oddspapi_lang)
        sd = SportsDataIOClient(http, tracker, s.sportsdataio_api_key, s.sportsdataio_base_url)
        print("=== OddsPapi REST ===")
        await test_oddspapi(op, s.exchange_list)
        if not args.skip_ws:
            print("=== OddsPapi WebSocket ===")
            await test_oddspapi_ws(s, args.ws_seconds)
        print("=== SportsDataIO REST ===")
        await test_sportsdataio(sd, s.sportsdataio_soccer_competition)

    report = write_report()
    passed = sum(r["ok"] is True for r in results)
    failed = sum(r["ok"] is False for r in results)
    skipped = sum(r["ok"] is None for r in results)
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped. Report: {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
