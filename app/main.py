import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.api import admin, exchanges, fixtures, health, live, stats, vendors
from app.api.tags import OPENAPI_TAGS
from app.config import get_settings
from app.db import create_tables, make_engine, make_session_factory
from app.models import Fixture
from app.providers.oddspapi import OddsPapiClient
from app.providers.sportsdataio import SportsDataIOClient
from app.services import jobs
from app.services.latency import LatencyTracker
from app.services.live_hub import LiveHub
from app.services.normalize import extract_result_score, parse_oddspapi_fixture
from app.services.oddspapi_ws import OddsPapiStream
from app.state import AppState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def build_stream(state: AppState) -> OddsPapiStream:
    s = state.settings

    async def on_fixture_update(payload: dict) -> None:
        channel = payload.pop("channel", None)
        async with state.session_factory() as session:
            if channel == "fixtures":
                parsed = parse_oddspapi_fixture(payload)
                if parsed:
                    await jobs.upsert_fixture(session, parsed, s, state.hub)
            else:  # scores
                fx = (await session.execute(select(Fixture).where(
                    Fixture.oddspapi_id == str(payload.get("fixtureId"))))).scalar_one_or_none()
                if fx is None:
                    return
                scores = payload.get("scores", payload)
                fx.scores = scores
                home, away = extract_result_score(scores)
                if home is not None:
                    fx.home_score, fx.away_score = home, away
            await session.commit()

    async def on_snapshot_required(channels: list[str]) -> None:
        log.info("snapshot required for %s -> REST resync", channels)
        asyncio.create_task(jobs.sync_fixtures(state.session_factory, state.oddspapi, s, state.hub))

    return OddsPapiStream(s.oddspapi_ws_url, s.oddspapi_api_key, s.ws_channel_list, state.tracker, state.hub,
                          filters=s.ws_filters, on_fixture_update=on_fixture_update, on_snapshot_required=on_snapshot_required)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    engine = make_engine(s.database_url)
    await create_tables(engine)
    tracker = LatencyTracker()
    http = httpx.AsyncClient()
    state = AppState(
        settings=s, engine=engine, session_factory=make_session_factory(engine), http=http,
        tracker=tracker, hub=LiveHub(),
        oddspapi=OddsPapiClient(http, tracker, s.oddspapi_api_key, s.oddspapi_base_url, s.oddspapi_lang),
        sportsdataio=SportsDataIOClient(http, tracker, s.sportsdataio_api_key, s.sportsdataio_base_url),
    )
    app.state.ctx = state

    if s.background_jobs_enabled:
        sf = state.session_factory
        state.tasks.append(asyncio.create_task(jobs.run_periodic("flush_latency", 60, jobs.flush_latency, sf, tracker)))
        if state.oddspapi.configured:
            state.tasks += [
                asyncio.create_task(jobs.run_periodic("sync_fixtures", s.fixture_sync_interval_sec,
                                                      jobs.sync_fixtures, sf, state.oddspapi, s, state.hub)),
                asyncio.create_task(jobs.run_periodic("activate_markets", s.activation_interval_sec,
                                                      jobs.activate_markets, sf, state.oddspapi, s, state.hub)),
            ]
            if s.oddspapi_ws_enabled:
                state.stream = build_stream(state)
                state.tasks.append(asyncio.create_task(state.stream.run()))
        else:
            log.warning("ODDSPAPI_API_KEY not set - background sync/WebSocket disabled")

    yield

    for t in state.tasks:
        t.cancel()
    await asyncio.gather(*state.tasks, return_exceptions=True)
    await jobs.flush_latency(state.session_factory, tracker)
    await http.aclose()
    await engine.dispose()


DESCRIPTION = """
Sports data and prediction-market backend for **OpinionKings**. It uses two vendors; each has its own
section below, followed by the endpoints for our own data.

---

## 1. OddsPapi: prediction-market exchanges
Base URL `https://v5.oddspapi.io`, key `ODDSPAPI_API_KEY`, 14-day B2B trial.
Provides fixtures, live status, scores, **odds with order-book depth**, and each exchange's own id for a match.
Exchanges: `kalshi`, `polymarket`, `polymarket.us`, `prophetx`, `limitless-ex` (also on the trial:
`betfair-ex`, `matchbook`, `4casters`, `overtime.io`, `draftkings-predictions`).
Sport ids: 10 soccer, 11 basketball, 14 American football, **27 cricket**.

1. `GET /exchanges/sports`: every sport and its id.
2. `GET /exchanges/kalshi/fixtures?sport_id=10&status=upcoming`: matches listed on Kalshi.
3. `GET /exchanges/kalshi/fixtures/{fixture_id}/odds`: live prices for one match.
4. `GET /exchanges/kalshi/mapping?fixture_ids={fixture_id}`: Kalshi's own ticker for that match.
5. `GET /vendors/oddspapi/{path}`: any other OddsPapi endpoint, untouched.

## 2. SportsDataIO: scores and stats
Base URL `https://api.sportsdata.io`, key `SPORTSDATAIO_API_KEY` (**not configured yet**; the endpoints return 503).
Provides schedules, live and final scores, box scores, lineups and injuries. The free trial covers soccer for
UEFA Champions League (competition 3) only, plus NBA/MLB/NHL.

1. `GET /stats/soccer/games?competition=3&day=YYYY-MM-DD`
2. `GET /stats/soccer/box-scores?day=YYYY-MM-DD`
3. `GET /stats/nba/games?day=YYYY-MM-DD`
4. `GET /vendors/sportsdataio/{path}`: any other SportsDataIO endpoint, untouched.

## 3. Our backend
* `GET /fixtures?lifecycle=ACTIVE`: matches whose markets were activated (24 h before start).
* `WS /ws/live?fixture_id=...`: real-time scores, odds and lifecycle updates.
* `POST /admin/*`: run the background jobs by hand.
"""


app = FastAPI(title="OpinionKings Sports Data Backend", version="0.1.0", description=DESCRIPTION,
              openapi_tags=OPENAPI_TAGS, lifespan=lifespan)
app.include_router(exchanges.router)
app.include_router(stats.router)
app.include_router(vendors.router)
app.include_router(fixtures.router)
app.include_router(live.router)
app.include_router(admin.router)
app.include_router(health.router)
