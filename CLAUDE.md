# CLAUDE.md: project handoff and progress log

Read this first in every new session. It records what has been done, what was verified against the real vendor
APIs, what is still broken, and what to do next. **Update the progress log at the end of every session.**
User-facing docs live in `README.md`.

## Project in one paragraph
FastAPI backend for **OpinionKings** (prediction-market product). Two vendors:
1. **OddsPapi** (v5, B2B trial): fixtures, scores, odds with order-book depth, and each exchange's own id for a match
   on Kalshi / Polymarket / Polymarket US / ProphetX / Limitless. REST + WebSocket.
2. **SportsDataIO**: scores, box scores, lineups, injuries. **No key yet.**
Our backend stores fixtures (SQLite), runs a market lifecycle (SCHEDULED → ACTIVE 24 h before start → LIVE → FINISHED),
and pushes live updates to the frontend over `/ws/live`. Purpose right now: November proof of concept plus vendor evaluation
(latency/reliability numbers in `/metrics/latency`).

## How to run / check things
- Run: `run project.bat` → http://localhost:8000/docs. Restart after any `.env` change (`--reload` ignores `.env`).
- Unit tests: `.venv\Scripts\python -m pytest -q` (19 tests, vendors mocked; all pass as of 2026-11-17).
- Live vendor check: `.venv\Scripts\python -m scripts.test_apis [--skip-ws] [--ws-seconds 30]`.
- Regenerate docs: `python -m scripts.export_openapi` (→ `docs/openapi.json`),
  `python -m scripts.export_endpoints_csv` (→ `docs/api_endpoints.csv`; calls real APIs and **runs
  `POST /admin/sync-fixtures` once**).
- Vendor docs: https://docs.oddspapi.io/llms-full.txt (whole OddsPapi doc set as one text file; grep it).

## Conventions
- Secrets only in `.env` (gitignored). Never commit keys, never hard-code them.
- Swagger sections are defined in `app/api/tags.py`. Order: OddsPapi → SportsDataIO → Backend. New endpoints must use
  one of those tag constants.
- After changing endpoints: re-run `export_openapi` and `export_endpoints_csv`, and update README.

## Current state (2026-11-17)

| Item | State |
|---|---|
| `ODDSPAPI_API_KEY` | Set in `.env`. 14-day trial started 2026-11-17 (ends ~2026-12-01) |
| `SPORTSDATAIO_API_KEY` | **Missing**. All `/stats/*` and `/vendors/sportsdataio/*` return 503 |
| `BACKGROUND_JOBS_ENABLED` | `false` (user wanted on-demand only). `true` also starts the WebSocket |
| OddsPapi REST | Verified with live data: sports, bookmakers, tournaments, fixtures, live/today, odds, mapping |
| OddsPapi WebSocket | Logs in with filters; **drops with 4002 backpressure** (see issue 1) |
| Cricket | OddsPapi `sportId = 27` (64 fixtures on exchanges). Not in `SPORT_IDS` yet |
| Lifecycle | Verified live: SCHEDULED → ACTIVE and → FINISHED transitions happen |

## Progress log

### 2026-11-17: session 1 (OddsPapi key, first live verification, docs)
Done:
- Added the OddsPapi key to `.env`. Ran `scripts.test_apis` against the real API.
- **Fixed `normalize.parse_oddspapi_fixture`**: v5 nests fields (`sport.sportId`, `participants.participant1Name`,
  `status.statusId`, `tournament.*`). Before the fix every fixture was "TBD vs TBD" with `statusId=None`, so the
  lifecycle never saw live/finished/cancelled. It now reads nested fields with a flat fallback (the WebSocket and tests may use flat).
- **WebSocket login filters**: added `Settings.ws_filters` (`sportIds` = `SPORT_IDS`, `bookmakers` = `EXCHANGES`), passed
  in `app/main.py` and `scripts/test_apis.py`. Before this we subscribed to every bookmaker and sport.
- `scripts/test_apis.py`: `/fixtures/live` and `/fixtures/today` need `sportId` (they returned 400 without it); now passes `sport_id=10`.
- Swagger regrouped into vendor sections (`app/api/tags.py`); description in `app/main.py` rewritten in three parts.
- New `scripts/export_endpoints_csv.py` → `docs/api_endpoints.csv` (every endpoint, params, curl, real response).
- README restructured: Vendor 1 OddsPapi / Vendor 2 SportsDataIO / Backend.
- `zstandard` was pip-installed into `.venv` for an experiment. **Not** in `requirements.txt`, not used by the app.

Verified facts (live):
- `/fixtures` per sport on our 5 exchanges: soccer 973, basketball 1068, cricket 64.
- Fixture payload `bookmakers.<slug>` already contains `bookmakerFixtureId` (e.g. Kalshi
  `KXINTLFRIENDLYGAME-26NOV17KSAUZB`), `fixturePath`, `hasOdds`, `staleOdds`, `suspended`.
- Odds payload: `odds.<bookmaker>.<fixtureId:bookmaker:outcomeId:playerId>` → `price`, `limit`, `meta.back[]/lay[]`
  (`price`, `cents`, `size`, `limit`), `bookmakerMarketId`, `bookmakerOutcomeId`, `betslip`, `changedAt`.
- WS `login_ok` echoes the accepted filters and `resume.resumeWindowMs = 60000`.
- REST latency from here: about 170–500 ms for most calls, about 1 s for big fixture lists.

## Known issues / open problems (priority order)

1. **WebSocket 4002 backpressure.** Even with filters, the `odds` channel sends about 450 frames/s (about 1 MB/s JSON)
   for Polymarket/Kalshi order books. The connection drops after about 20–30 s, reconnects, and odds arrive about 10 s late.
   Options: (a) `receiveType: "zstd"` (5–6× smaller; decode each binary frame with `zstandard` dictless decompress;
   check `login_ok.receiveType` because the server may downgrade). My test script hung, so this is unverified.
   (b) Move JSON parsing/processing off the receive loop (queue + worker). (c) Narrow filters (`tournamentIds`) or drop
   `odds` from `ODDSPAPI_WS_CHANNELS` and poll REST odds only for ACTIVE fixtures.
2. **`activate_markets` is slow** (~1 s per fixture: 1 odds call + one `/fixtures/mapping` call per exchange, sequential).
   Fix: use `bookmakers.<slug>.bookmakerFixtureId` / `hasOdds` from the `/fixtures` response that `sync_fixtures` already
   fetches; skip the per-exchange mapping calls. Also saves trial quota.
3. **`scripts/test_apis.py` picks a poor sample fixture** (earliest upcoming, may have no exchange pricing). Should pick
   one where `bookmakers.<slug>.hasOdds` is true.
4. **SportsDataIO untested**: needs the key. Then run `scripts.test_apis`, inspect `samples/`, and tighten
   `parse_sportsdataio_soccer_game`. Cricket paths aren't in their public OpenAPI files, so ask the vendor.
5. Old rows in `sportdata.db` may still say "TBD" from before the normalizer fix (sync updates them over time). Deleting
   `sportdata.db` is safe; it is recreated on startup.

## Next steps (suggested)
- [ ] Fix issue 2 (fast activation from the fixtures payload).
- [ ] Fix issue 1 (zstd or processing queue), then turn `BACKGROUND_JOBS_ENABLED=true` back on.
- [ ] Add cricket: `SPORT_IDS=10,11,14,27`.
- [ ] Decide whether to add trial bookmakers `betfair-ex`, `matchbook`, `draftkings-predictions`, `4casters`, `overtime.io`
      to `EXCHANGES`. The `Exchange` enum in `app/api/exchanges.py` lacks `4casters` and `overtime.io`, and lists
      `novig.us`, `gemini`, `myriad`, `robinhood`, `crypto.com`, which are **not** on our trial.
- [ ] Get the SportsDataIO key; verify its endpoints.
- [ ] Vendor recommendation report from `/metrics/latency` + `reports/`.
- [ ] Production: Postgres + Alembic, Redis for `live_hub`, API auth, remove `/vendors/*` passthrough.
