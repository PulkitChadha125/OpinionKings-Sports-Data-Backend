"""Per-exchange data endpoints (Kalshi, Polymarket, ProphetX, ...).

All exchange data comes through OddsPapi, which aggregates prediction-market
exchanges as "bookmakers". These endpoints wrap it so the frontend / Swagger
users can pick an exchange from a dropdown and fetch its data.
"""

from enum import Enum

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_ctx, provider_http_error
from app.providers.base import ProviderError
from app.services.normalize import as_list, parse_oddspapi_fixture
from app.state import AppState

router = APIRouter(prefix="/exchanges", tags=["exchanges"])


class Exchange(str, Enum):
    """OddsPapi bookmaker slugs for prediction-market exchanges."""
    kalshi = "kalshi"
    polymarket = "polymarket"
    polymarket_us = "polymarket.us"
    prophetx = "prophetx"
    limitless = "limitless-ex"
    novig = "novig.us"
    gemini = "gemini"
    myriad = "myriad"
    robinhood = "robinhood"
    crypto_com = "crypto.com"
    draftkings_predictions = "draftkings-predictions"
    betfair_exchange = "betfair-ex"
    matchbook = "matchbook"


class Sport(int, Enum):
    """Common OddsPapi sport ids. Cricket's id: call GET /exchanges/sports."""
    soccer = 10
    basketball = 11
    american_football = 14


EXCHANGE_PATH = Path(..., description="Exchange (OddsPapi bookmaker slug)", examples=["kalshi"])
FIXTURE_PATH = Path(..., description="OddsPapi fixture id", examples=["id1000001761300517"])


@router.get("/sports", summary="List all sports (find the cricket sportId here)")
async def list_sports(ctx: AppState = Depends(get_ctx)):
    """Returns OddsPapi's sport catalogue. Use the `sportId` values in the other endpoints."""
    try:
        return await ctx.oddspapi.sports()
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("", summary="List supported exchanges and their metadata")
async def list_exchanges(ctx: AppState = Depends(get_ctx)):
    """Metadata (name, flags such as `staleOdds`) for every exchange in the `Exchange` enum."""
    try:
        return await ctx.oddspapi.bookmakers([e.value for e in Exchange])
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("/{exchange}/fixtures", summary="Fixtures listed on an exchange")
async def exchange_fixtures(
    exchange: Exchange = EXCHANGE_PATH,
    sport_id: int = Query(Sport.soccer.value, description="OddsPapi sportId (10 soccer, 11 basketball, 14 NFL; "
                                                          "cricket: see /exchanges/sports)"),
    tournament_id: int | None = Query(None, description="Optional OddsPapi tournamentId"),
    status: str = Query("all", pattern="^(all|upcoming|live)$", description="all | upcoming | live"),
    raw: bool = Query(False, description="Return the vendor payload untouched"),
    ctx: AppState = Depends(get_ctx),
):
    """Matches that have markets on the chosen exchange.

    Example: `GET /exchanges/kalshi/fixtures?sport_id=10&status=upcoming`
    """
    try:
        if status == "live":
            data = await ctx.oddspapi.fixtures_live(sport_id=sport_id, bookmakers=[exchange.value])
        else:
            data = await ctx.oddspapi.fixtures(sport_id=sport_id, tournament_id=tournament_id,
                                               status_id=0 if status == "upcoming" else None,
                                               bookmakers=[exchange.value])
    except ProviderError as exc:
        raise provider_http_error(exc)
    if raw:
        return data
    return [f for f in (parse_oddspapi_fixture(r) for r in as_list(data)) if f]


@router.get("/{exchange}/fixtures/{fixture_id}/odds", summary="Prices for a fixture on an exchange")
async def exchange_fixture_odds(exchange: Exchange = EXCHANGE_PATH, fixture_id: str = FIXTURE_PATH,
                                ctx: AppState = Depends(get_ctx)):
    """Current odds/prices for every market of this fixture on the exchange
    (`odds[exchange][oddsId]`). Exchanges also carry back/lay ladders and liquidity.

    Example: `GET /exchanges/polymarket/fixtures/id1000001761300517/odds`
    """
    try:
        return await ctx.oddspapi.fixture_odds(fixture_id, bookmakers=[exchange.value])
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("/{exchange}/mapping", summary="Map OddsPapi fixtures to the exchange's own ids")
async def exchange_mapping(
    exchange: Exchange = EXCHANGE_PATH,
    fixture_ids: str = Query(..., description="Comma-separated OddsPapi fixture ids",
                             examples=["id1000001761300517"]),
    ctx: AppState = Depends(get_ctx),
):
    """Returns the exchange-native identifier (e.g. Kalshi event ticker, Polymarket market slug)
    for each fixture - this is how a match is linked to its tradable contract.

    Example: `GET /exchanges/kalshi/mapping?fixture_ids=id1000001761300517`
    """
    try:
        return await ctx.oddspapi.fixtures_mapping(exchange.value, [f.strip() for f in fixture_ids.split(",")])
    except ProviderError as exc:
        raise provider_http_error(exc)
