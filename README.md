# OpinionKings – Sports Data Backend

FastAPI backend that pulls **prediction-market data** and **sports data** from two vendors,
normalizes it, automatically activates markets 24 h before kick-off, and streams live updates
to the OpinionKings frontend.

| # | Vendor | What we use it for | Status |
|---|---|---|---|
| 1 | **OddsPapi** (v5 / B2B trial) | Fixtures, live status, scores, odds with order-book depth, and each exchange's own id for a match on Kalshi, Polymarket, Polymarket US, ProphetX, Limitless … (REST + WebSocket) | ✅ Key configured, verified with live data |
| 2 | **SportsDataIO** | Live scores, box scores (player/team stats), lineups, injuries, historical data | ⏳ No key yet (endpoints return 503) |

> November proof of concept and vendor-evaluation build. It also measures each vendor's latency and reliability for the vendor recommendation.
> **Progress log, known issues and next steps: [`CLAUDE.md`](CLAUDE.md).**

---

## 1. Quick start (Windows)

1. Double-click **`run project.bat`**. It creates `.venv`, installs `requirements.txt`, creates `.env` from
   `.env.example` the first time, and starts the server at **http://localhost:8000**.
2. Keys go in `.env` (gitignored, never commit it):
   ```env
   ODDSPAPI_API_KEY=...        # already set
   SPORTSDATAIO_API_KEY=...    # still needed
   ```
3. Restart `run project.bat` after **any** `.env` change. `--reload` only watches `.py` files.

| URL | What |
|---|---|
| http://localhost:8000/docs | **Swagger UI**: OddsPapi sections first, then SportsDataIO, then Backend |
| http://localhost:8000/redoc | ReDoc (read-only docs) |
| http://localhost:8000/openapi.json | OpenAPI spec (also saved to `docs/openapi.json`) |
| http://localhost:8000/health | Status, key configuration, WebSocket connection |

**Background jobs on/off:** `BACKGROUND_JOBS_ENABLED=false` in `.env` turns off the fixture sync, market activation
**and** the OddsPapi WebSocket, so the API only answers what you call. It is currently `false`.

Manual setup instead of the .bat:
```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

## 2. Testing

```bash
.venv\Scripts\python -m pytest -q                       # 19 unit/integration tests (vendors mocked)
.venv\Scripts\python -m scripts.test_apis               # hits every REAL vendor endpoint + 30 s WebSocket
.venv\Scripts\python -m scripts.test_apis --skip-ws     # REST only
.venv\Scripts\python -m scripts.export_endpoints_csv    # docs/api_endpoints.csv: every endpoint, params, real response
.venv\Scripts\python -m scripts.export_openapi          # docs/openapi.json
```
`test apis.bat` runs the unit tests and the live vendor test. The live test saves raw responses to `samples/` and a
report to `reports/` (both gitignored).

**Endpoint reference:** [`docs/api_endpoints.csv`](docs/api_endpoints.csv) lists every endpoint with its parameters,
a ready-to-paste `curl` command and a real example response. Opens in Excel.

---

## 3. Vendor 1: OddsPapi (prediction-market exchanges)

| | |
|---|---|
| Base URL | `https://v5.oddspapi.io/{lang}`, header `X-API-Key` |
| WebSocket | `wss://v5.oddspapi.io/ws` |
| Docs | https://docs.oddspapi.io · full bundle: https://docs.oddspapi.io/llms-full.txt · status: https://oddspapi-v5.instatus.com/ |
| Trial | 14 days from 2026-11-17, pre-game + in-play |
| Bookmakers on trial | `kalshi`, `polymarket`, `polymarket.us`, `prophetx`, `limitless-ex`, `draftkings-predictions`, `betfair-ex`, `matchbook`, `4casters`, `overtime.io` |
| Tracked now (`EXCHANGES`) | `kalshi, polymarket, polymarket.us, prophetx, limitless-ex` |
| Sport ids | 10 soccer · 11 basketball · 14 American football · **27 cricket** |
| Rate limits | 10 req/s on odds endpoints, 200 req/min elsewhere |
| Code | `app/providers/oddspapi.py`, `app/services/oddspapi_ws.py`, `app/api/exchanges.py` |

### Endpoints (Swagger → *OddsPapi - …*)

| Step | Request | Returns |
|---|---|---|
| 1 | `GET /exchanges/sports` | All sports and their ids |
| 2 | `GET /exchanges` | Exchange metadata (name, `staleOdds` flag …) |
| 3 | `GET /exchanges/{exchange}/fixtures?sport_id=10&status=upcoming` | Matches listed on that exchange (`status`: all / upcoming / live; `raw=true` for the vendor payload, which includes `bookmakers.<exchange>.bookmakerFixtureId`) |
| 4 | `GET /exchanges/{exchange}/fixtures/{fixture_id}/odds` | Prices for every market of the match, with back/lay order-book depth |
| 5 | `GET /exchanges/{exchange}/mapping?fixture_ids=id1,id2` | The exchange's own id for the match (e.g. Kalshi `KXINTLFRIENDLYGAME-26NOV17KSAUZB`) |
| – | `GET /vendors/oddspapi/{path}?…` | Any OddsPapi GET, untouched (trial only) |

```bash
curl "http://localhost:8000/exchanges/kalshi/fixtures?sport_id=10&status=upcoming"
curl "http://localhost:8000/exchanges/polymarket/fixtures?sport_id=11&status=live"
curl "http://localhost:8000/exchanges/kalshi/fixtures?sport_id=27&status=upcoming"        # cricket
curl "http://localhost:8000/exchanges/kalshi/fixtures/FIXTURE_ID/odds"
curl "http://localhost:8000/exchanges/kalshi/mapping?fixture_ids=FIXTURE_ID"
curl "http://localhost:8000/vendors/oddspapi/fixtures/today?sportId=10"                    # sportId is required
```

### OddsPapi payload notes (verified 2026-11-17)
- v5 fixtures are **nested**: `sport.sportId`, `tournament.tournamentName`, `participants.participant1Name`,
  `status.statusId`, `startTime` (epoch seconds). `services/normalize.py::parse_oddspapi_fixture` reads nested fields
  and falls back to flat ones.
- `/fixtures/live` and `/fixtures/today` **require** `sportId` or `tournamentId` (400 otherwise).
- Each fixture's `bookmakers.<slug>` block already includes `bookmakerFixtureId`, `fixturePath`, `hasOdds`, `staleOdds`,
  so `/fixtures/mapping` calls are often unnecessary.
- Odds response: `odds.<bookmaker>.<outcomeKey>` → `price`, `limit`, `meta.back[]` / `meta.lay[]` (price, cents, size),
  `bookmakerMarketId`, `bookmakerOutcomeId`, `betslip` URL.
- WebSocket login takes `sportIds`, `tournamentIds`, `fixtureIds`, `bookmakers` filters and
  `receiveType` (`json` | `binary` | `zstd` | `zstd-dict`). We send `sportIds` + `bookmakers` (`Settings.ws_filters`).

---

## 4. Vendor 2: SportsDataIO (scores and stats)

| | |
|---|---|
| Base URL | `https://api.sportsdata.io` |
| Key | `SPORTSDATAIO_API_KEY` (**not configured yet**) |
| Trial coverage | Soccer for UEFA Champions League (competition 3) only, plus NBA / MLB / NHL |
| Code | `app/providers/sportsdataio.py`, `app/api/stats.py` |

### Endpoints (Swagger → *SportsDataIO - …*)

```bash
curl "http://localhost:8000/stats/soccer/competitions"
curl "http://localhost:8000/stats/soccer/games?competition=3&day=2026-11-25"   # schedule + live/final scores
curl "http://localhost:8000/stats/soccer/box-scores?day=2026-11-25"            # player & team stats
curl "http://localhost:8000/stats/soccer/box-score/GAME_ID"
curl "http://localhost:8000/stats/soccer/lineups?day=2026-11-25"
curl "http://localhost:8000/stats/soccer/injuries"
curl "http://localhost:8000/stats/nba/games?day=2026-11-25"                    # nba | mlb | nhl
curl "http://localhost:8000/stats/nba/injuries"
curl "http://localhost:8000/vendors/sportsdataio/v4/soccer/scores/json/Competitions"   # raw passthrough
```
Payload shapes are **not verified yet**. Once the key is in, run `scripts.test_apis`, check `samples/`, and tighten
`services/normalize.py::parse_sportsdataio_soccer_game`.

---

## 5. Our backend (combines both vendors)

### Market lifecycle (automated)

```
SCHEDULED ──(start ≤ 24h & exchange markets found)──► ACTIVE ──► LIVE ──► FINISHED
    │                     └─(no markets yet)──► PENDING_MAPPING (retried every 5 min)
    ├── vendor cancels/removes ──────────────► CANCELLED (reinstated if vendor restores it)
    └── start moved > 12h out ───────────────► POSTPONED ──(back inside window)──► SCHEDULED → ACTIVE
        start moved outside window ──────────► SCHEDULED (deactivated)
```

Background jobs (run when `BACKGROUND_JOBS_ENABLED=true` and `ODDSPAPI_API_KEY` is set):

| Job | Every | Does |
|---|---|---|
| `sync_fixtures` | 10 min | Pulls fixtures for `SPORT_IDS` listed on your `EXCHANGES`, upserts them, applies cancel/postpone/reschedule rules (~2,270 fixtures seen per run) |
| `activate_markets` | 5 min | For matches starting within 24 h: finds which exchanges price them, stores the exchange ids, sets ACTIVE / PENDING_MAPPING. **Slow: about 1 s per fixture** |
| WebSocket consumer | live | OddsPapi `fixtures`, `scores`, `odds` → DB + live hub; auto-reconnect with resume cursors |
| `flush_latency` | 1 min | Saves per-minute latency stats (p50/p95/max) |

Run them by hand: `POST /admin/sync-fixtures`, `POST /admin/activate-markets`,
`POST /admin/link-sportsdataio` (fuzzy-links SportsDataIO games to our fixtures by team names and kick-off time).

### Fixture API
```bash
curl "http://localhost:8000/fixtures?lifecycle=ACTIVE"
curl "http://localhost:8000/fixtures?sport_id=10&limit=20"
curl "http://localhost:8000/fixtures/FIXTURE_ID"          # detail: scores + lifecycle audit trail
```

### Live WebSocket for the frontend
`ws://localhost:8000/ws/live?fixture_id=<oddspapi id>` for one match, or `ws://localhost:8000/ws/live` for everything.
Needs background jobs on (the OddsPapi stream feeds it).

```js
const ws = new WebSocket("ws://localhost:8000/ws/live?fixture_id=FIXTURE_ID");
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data); // msg.type: "scores" | "fixtures" | "odds" | "lifecycle" | "heartbeat"
  console.log(msg.type, msg.payload);
};
```

### Vendor evaluation metrics
```bash
curl http://localhost:8000/metrics/latency
curl "http://localhost:8000/metrics/latency/history?provider=oddspapi"
```
REST latency is round-trip time. WebSocket latency is `now - vendor ts`.

---

## 6. Project structure

```
app/
  main.py               FastAPI app, Swagger description, startup of jobs + WebSocket
  config.py             Settings from .env (incl. ws_filters)
  models.py             Fixture, ExchangeMarket, LifecycleEvent, LatencySummary
  db.py                 SQLAlchemy async engine (SQLite default, Postgres via DATABASE_URL)
  providers/
    base.py             HTTP client with retries, 429 handling, latency recording
    oddspapi.py         OddsPapi v5 REST client                       ← vendor 1
    sportsdataio.py     SportsDataIO REST client                      ← vendor 2
  services/
    oddspapi_ws.py      OddsPapi WebSocket consumer (login filters, resume cursors)
    jobs.py             fixture sync, market activation, SportsDataIO linking, latency flush
    lifecycle.py        state machine rules (pure functions, unit tested)
    mapping.py          exchange id lookup + fuzzy cross-vendor matching
    normalize.py        vendor payload → canonical fields
    live_hub.py         in-process pub/sub for /ws/live
    latency.py          latency/staleness tracker
  api/
    tags.py             Swagger section names + descriptions (OddsPapi / SportsDataIO / Backend)
    exchanges.py        OddsPapi endpoints
    stats.py            SportsDataIO endpoints
    vendors.py          raw passthrough for both vendors
    fixtures.py, live.py, admin.py, health.py   our backend
scripts/
  test_apis.py              live vendor smoke test + report
  export_openapi.py         writes docs/openapi.json
  export_endpoints_csv.py   writes docs/api_endpoints.csv
docs/
  openapi.json              Swagger/OpenAPI spec (machine-readable API description)
  api_endpoints.csv         endpoint reference with real example responses
tests/                      pytest suite (vendors mocked with respx)
CLAUDE.md                   progress log, known issues, next steps
```

## 7. Configuration (`.env`)

| Variable | Current | Notes |
|---|---|---|
| `ODDSPAPI_API_KEY` | set | Vendor 1 |
| `SPORTSDATAIO_API_KEY` | empty | Vendor 2 |
| `EXCHANGES` | `kalshi,polymarket,polymarket.us,prophetx,limitless-ex` | OddsPapi bookmaker slugs to track |
| `SPORT_IDS` | `10,11,14` | Add `27` for cricket |
| `ODDSPAPI_WS_CHANNELS` | `fixtures,scores,odds` | Remove `odds` to avoid the backpressure disconnects (see CLAUDE.md) |
| `BACKGROUND_JOBS_ENABLED` | `false` | `true` = sync, activation and WebSocket run automatically |
| `ACTIVATION_WINDOW_HOURS` | `24` | Activate markets this long before start |
| `DATABASE_URL` | SQLite file | `postgresql+asyncpg://…` for Postgres |
