"""Swagger section names. Swagger UI shows tags in the order of OPENAPI_TAGS:
OddsPapi sections first, then SportsDataIO, then our own backend endpoints."""

ODDSPAPI_EXCHANGES = "OddsPapi - Exchanges, fixtures & odds"
ODDSPAPI_RAW = "OddsPapi - Raw passthrough (trial only)"
SDIO_STATS = "SportsDataIO - Scores, stats, lineups & injuries"
SDIO_RAW = "SportsDataIO - Raw passthrough (trial only)"
BACKEND_FIXTURES = "Backend - Fixtures & market lifecycle"
BACKEND_LIVE = "Backend - Live WebSocket"
BACKEND_ADMIN = "Backend - Admin jobs"
BACKEND_HEALTH = "Backend - Health & vendor metrics"

OPENAPI_TAGS = [
    {"name": ODDSPAPI_EXCHANGES, "description":
        "**Vendor 1: OddsPapi** (`https://v5.oddspapi.io`, key `ODDSPAPI_API_KEY`). Prediction-market data: "
        "matches listed on Kalshi, Polymarket, Polymarket US, ProphetX, Limitless..., live prices with order-book "
        "depth, and each exchange's own id for a match (Kalshi ticker, Polymarket slug). Sport ids: 10 soccer, "
        "11 basketball, 14 American football, 27 cricket."},
    {"name": ODDSPAPI_RAW, "description":
        "Any OddsPapi GET endpoint, with the key added on the server side. Example: path `fixtures/today`, "
        "query `sportId=10`. Docs: https://docs.oddspapi.io. Remove in production."},
    {"name": SDIO_STATS, "description":
        "**Vendor 2: SportsDataIO** (`https://api.sportsdata.io`, key `SPORTSDATAIO_API_KEY`). Game data: schedules, "
        "live and final scores, box scores (player and team stats), lineups, injuries. The free trial covers soccer for "
        "UEFA Champions League (competition 3) only, plus NBA/MLB/NHL. Returns 503 until the key is set."},
    {"name": SDIO_RAW, "description":
        "Any SportsDataIO GET endpoint, with the key added on the server side. Example path: "
        "`v4/soccer/scores/json/Competitions`. Remove in production."},
    {"name": BACKEND_FIXTURES, "description":
        "Our own database: fixtures merged from both vendors, with lifecycle state "
        "(SCHEDULED, ACTIVE, LIVE, FINISHED, ...) and the exchange markets mapped to each one."},
    {"name": BACKEND_LIVE, "description": "WebSocket `/ws/live`. Swagger can't run WebSockets; see the README."},
    {"name": BACKEND_ADMIN, "description": "Trigger the background jobs by hand."},
    {"name": BACKEND_HEALTH, "description": "Service status, key configuration and per-vendor latency metrics."},
]
