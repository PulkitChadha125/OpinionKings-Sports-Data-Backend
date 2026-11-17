# OpinionKings – Sports Data Backend

FastAPI backend that pulls **sports data** and **prediction-market data** from two vendors,
normalizes it, automatically activates markets 24 h before kick-off, and streams live
updates to the OpinionKings frontend.

| Vendor | What we use it for |
|---|---|
| **OddsPapi** (v5 / B2B trial) | Fixtures, live status, scores, odds, and **mapping matches to exchange contracts** on Kalshi, Polymarket, Polymarket US, ProphetX, Limitless … REST + WebSocket |
| **SportsDataIO** | Live scores, box scores (player/team stats), lineups, injuries, historical data |

> This is the November proof of concept and vendor-evaluation build. It also measures each vendor's latency and reliability, which the vendor recommendation needs.

---

## 1. Quick start (Windows)

1. Double-click **`run project.bat`**. It:
   - creates `.venv` (Python 3.12) if it doesn't exist,
   - installs everything in `requirements.txt` into `.venv`,
   - creates `.env` from `.env.example` the first time,
   - starts the server at **http://localhost:8000**.
2. Open `.env` and add the trial keys:
   ```env
   ODDSPAPI_API_KEY=your-oddspapi-key
   SPORTSDATAIO_API_KEY=your-sportsdataio-key
   ```
3. Restart `run project.bat`.

| URL | What |
|---|---|
| http://localhost:8000/docs | **Swagger UI** – try every endpoint in the browser |
| http://localhost:8000/redoc | ReDoc (read-only docs) |
| http://localhost:8000/openapi.json | OpenAPI spec (also exported to `docs/openapi.json`) |
| http://localhost:8000/health | Status, key configuration, WebSocket connection |

Manual setup instead of the .bat:
```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

## 2. Testing the APIs

Double-click **`test apis.bat`**, or run:

```bash
.venv\Scripts\python -m pytest -q                       # 19 unit / integration tests (vendors mocked)
.venv\Scripts\python -m scripts.test_apis               # hits every REAL vendor endpoint + 30s WebSocket
.venv\Scripts\python -m scripts.test_apis --skip-ws     # REST only
```

`scripts/test_apis.py`:
- calls every OddsPapi and SportsDataIO endpoint the backend depends on, and prints PASS/FAIL/SKIP with latency,
- finds the **cricket `sportId`** from `/sports` and tests cricket fixtures,
- picks an upcoming fixture and checks which exchanges price it, plus its Kalshi/Polymarket mapping,
- connects to the OddsPapi WebSocket and reports message counts and delivery delay per channel,
- saves every raw response to `samples/` (to learn the payload shapes) and writes a markdown report to `reports/`.

---

## 3. How to fetch data from each exchange (Swagger → *exchanges*)

Each endpoint has a **dropdown** of exchanges: `kalshi`, `polymarket`, `polymarket.us`, `prophetx`,
`limitless-ex`, `novig.us`, `gemini`, `myriad`, `robinhood`, `crypto.com`, `draftkings-predictions`,
`betfair-ex`, `matchbook`.

| Step | Request | Returns |
|---|---|---|
| 1 | `GET /exchanges/sports` | All sports + ids (find cricket) |
| 2 | `GET /exchanges` | Exchange metadata (name, `staleOdds` flag …) |
| 3 | `GET /exchanges/{exchange}/fixtures?sport_id=10&status=upcoming` | Matches listed on that exchange (`status`: all / upcoming / live; `raw=true` for the vendor payload) |
| 4 | `GET /exchanges/{exchange}/fixtures/{fixture_id}/odds` | Current prices for every market of the match on that exchange |
| 5 | `GET /exchanges/{exchange}/mapping?fixture_ids=id1,id2` | The exchange's own id for the match (Kalshi ticker, Polymarket slug …) |

### Examples

```bash
# Upcoming soccer matches tradable on Kalshi
curl "http://localhost:8000/exchanges/kalshi/fixtures?sport_id=10&status=upcoming"

# Live basketball matches on Polymarket
curl "http://localhost:8000/exchanges/polymarket/fixtures?sport_id=11&status=live"

# Prices for one match on ProphetX
curl "http://localhost:8000/exchanges/prophetx/fixtures/id1000001761300517/odds"

# Which Kalshi contract is this match?
curl "http://localhost:8000/exchanges/kalshi/mapping?fixture_ids=id1000001761300517"
```

```python
import httpx

api = httpx.Client(base_url="http://localhost:8000")
for exchange in ["kalshi", "polymarket", "prophetx"]:
    matches = api.get(f"/exchanges/{exchange}/fixtures", params={"sport_id": 10, "status": "upcoming"}).json()
    print(exchange, len(matches), "matches")
    if matches:
        fid = matches[0]["oddspapi_id"]
        odds = api.get(f"/exchanges/{exchange}/fixtures/{fid}/odds").json()
        mapping = api.get(f"/exchanges/{exchange}/mapping", params={"fixture_ids": fid}).json()
```

### Stats (Swagger → *stats (SportsDataIO)*)

```bash
curl "http://localhost:8000/stats/soccer/competitions"
curl "http://localhost:8000/stats/soccer/games?competition=3&day=2026-11-25"   # schedule + live/final scores
curl "http://localhost:8000/stats/soccer/box-scores?day=2026-11-25"            # player & team stats
curl "http://localhost:8000/stats/soccer/lineups?day=2026-11-25"
curl "http://localhost:8000/stats/soccer/injuries"
curl "http://localhost:8000/stats/nba/games?day=2026-11-25"
```
The SportsDataIO free trial covers soccer for the **UEFA Champions League (competition 3)** only.

### Raw vendor passthrough (trial only)

Any vendor GET endpoint, with the key added on the server side:
```bash
curl "http://localhost:8000/vendors/oddspapi/fixtures/today?sportId=10"
curl "http://localhost:8000/vendors/sportsdataio/v4/soccer/scores/json/Competitions"
```

---

## 4. Our own data: fixtures, automation and the live stream

### Market lifecycle (automated)

```
SCHEDULED ──(start ≤ 24h & exchange markets found)──► ACTIVE ──► LIVE ──► FINISHED
    │                     └─(no markets yet)──► PENDING_MAPPING (retried every 5 min)
    ├── vendor cancels/removes ──────────────► CANCELLED (reinstated if vendor restores it)
    └── start moved > 12h out ───────────────► POSTPONED ──(back inside window)──► SCHEDULED → ACTIVE
        start moved outside window ──────────► SCHEDULED (deactivated)
```

Background jobs (start automatically when `ODDSPAPI_API_KEY` is set):

| Job | Every | Does |
|---|---|---|
| `sync_fixtures` | 10 min | Pulls fixtures for `SPORT_IDS` that are listed on your `EXCHANGES`, upserts them, applies cancel/postpone/reschedule rules |
| `activate_markets` | 5 min | For matches starting within 24 h: finds which exchanges price them, stores the exchange ids, sets ACTIVE / PENDING_MAPPING |
| WebSocket consumer | live | OddsPapi `fixtures`, `scores`, `odds` channels → DB + live hub; auto-reconnect with resume cursors |
| `flush_latency` | 1 min | Saves per-minute latency stats (p50/p95/max) for the vendor report |

Trigger them by hand: `POST /admin/sync-fixtures`, `POST /admin/activate-markets`,
`POST /admin/link-sportsdataio` (fuzzy-links SportsDataIO games to our fixtures by team names and kick-off time).

### Fixture API

```bash
curl "http://localhost:8000/fixtures?lifecycle=ACTIVE"          # tradable matches + their exchange markets
curl "http://localhost:8000/fixtures?sport_id=10"
curl "http://localhost:8000/fixtures/id1000001761300517"        # detail: scores + lifecycle audit trail
```

### Live WebSocket for the frontend

`ws://localhost:8000/ws/live?fixture_id=<oddspapi id>` for one match, or `ws://localhost:8000/ws/live` for everything.
(Swagger can't run WebSockets, so test with the snippet below.)

```js
const ws = new WebSocket("ws://localhost:8000/ws/live?fixture_id=id1000001761300517");
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  // msg.type: "scores" | "fixtures" | "odds" | "lifecycle" | "heartbeat"
  console.log(msg.type, msg.payload);
};
```
```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/ws/live") as ws:
        async for raw in ws:
            print(json.loads(raw))

asyncio.run(main())
```

### Vendor evaluation metrics

```bash
curl http://localhost:8000/metrics/latency                                  # rolling p50/p95, errors, staleness per endpoint/channel
curl "http://localhost:8000/metrics/latency/history?provider=oddspapi"      # persisted per-minute history
```
REST latency is round-trip time. WebSocket latency is `now - vendor ts`, i.e. how long the vendor's update took to reach us.

---

## 5. Project structure

```
app/
  main.py               FastAPI app, Swagger metadata, startup of jobs + WebSocket
  config.py             Settings from .env
  models.py             Fixture, ExchangeMarket, LifecycleEvent, LatencySummary
  db.py                 SQLAlchemy async engine (SQLite by default, Postgres via DATABASE_URL)
  providers/
    base.py             HTTP client with retries, 429 handling, latency recording
    oddspapi.py         OddsPapi v5 REST client
    sportsdataio.py     SportsDataIO REST client
  services/
    oddspapi_ws.py      OddsPapi WebSocket consumer (login, resume cursors, snapshot_required)
    jobs.py             fixture sync, market activation, SportsDataIO linking, latency flush
    lifecycle.py        state machine rules (pure functions, unit tested)
    mapping.py          exchange contract discovery + fuzzy cross-vendor matching
    normalize.py        vendor payload → canonical fields
    live_hub.py         in-process pub/sub for /ws/live (swap for Redis when scaling out)
    latency.py          latency/staleness tracker
  api/                  routers: exchanges, stats, fixtures, live, admin, health, vendors
scripts/
  test_apis.py          live vendor smoke test + report
  export_openapi.py     writes docs/openapi.json
tests/                  pytest suite (vendors mocked with respx)
run project.bat         one-click setup + run
test apis.bat           unit tests + live vendor tests
```

## 6. Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `ODDSPAPI_API_KEY` | – | Required for exchange data |
| `SPORTSDATAIO_API_KEY` | – | Required for stats |
| `EXCHANGES` | `kalshi,polymarket,polymarket.us,prophetx,limitless-ex` | OddsPapi bookmaker slugs to track |
| `SPORT_IDS` | `10,11,14` | Add the cricket id printed by `scripts/test_apis.py` |
| `ODDSPAPI_WS_CHANNELS` | `fixtures,scores,odds` | Also available: `clocks`, `injuries`, `lineups`, `stats`, `events` … |
| `ACTIVATION_WINDOW_HOURS` | `24` | Activate markets this long before start |
| `DATABASE_URL` | SQLite file | `postgresql+asyncpg://…` for Postgres |
| `BACKGROUND_JOBS_ENABLED` | `true` | Turn off to use only the on-demand endpoints |

## 7. Known gaps / to confirm with vendors

- **OddsPapi payload shapes**: fixtures, odds and WebSocket envelopes follow the v5 docs. The normalizers accept several shapes. Run `scripts/test_apis.py` once the keys arrive, check `samples/`, then tighten `services/normalize.py`.
- **OddsPapi WebSocket filters**: the login currently sends channels only. Check the docs for login-time `sportIds`/`bookmakers` filters to reduce volume.
- **SportsDataIO cricket**: cricket is on their coverage list but not in the public OpenAPI files. Ask the vendor for the cricket (Global API) paths and call them via `/vendors/sportsdataio/...`.
- **SDX universal IDs**: the `sdx_id` column exists. Fill it once SDX access is set up; until then cross-vendor linking uses fuzzy matching.
- **Production**: move to Postgres with Alembic migrations, Redis pub/sub for `live_hub`, and authentication on the API. Remove `/vendors/*` passthrough.
