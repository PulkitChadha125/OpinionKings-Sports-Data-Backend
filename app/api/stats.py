"""Scores, stats, injuries and lineups from SportsDataIO."""

from datetime import date
from enum import Enum

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_ctx, provider_http_error
from app.providers.base import ProviderError
from app.state import AppState
from app.api import tags

router = APIRouter(prefix="/stats", tags=[tags.SDIO_STATS])


class League(str, Enum):
    nba = "nba"
    mlb = "mlb"
    nhl = "nhl"


COMP = Query(None, description="Soccer competition id/key. Default from .env "
                               "(trial: 3 = UEFA Champions League)", examples=["3"])
DAY = Query(None, description="YYYY-MM-DD, defaults to today", examples=["2026-11-25"])


async def _call(coro):
    try:
        return await coro
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("/soccer/competitions", summary="Soccer competitions available on your plan")
async def soccer_competitions(ctx: AppState = Depends(get_ctx)):
    return await _call(ctx.sportsdataio.soccer_competitions())


@router.get("/soccer/games", summary="Soccer games (schedule + live/final scores) for a date")
async def soccer_games(competition: str | None = COMP, day: date | None = DAY, ctx: AppState = Depends(get_ctx)):
    """Example: `GET /stats/soccer/games?competition=3&day=2026-11-25`"""
    comp = competition or ctx.settings.sportsdataio_soccer_competition
    return await _call(ctx.sportsdataio.soccer_games_by_date(comp, day or date.today()))


@router.get("/soccer/box-scores", summary="Live box scores (team + player stats) for a date")
async def soccer_box_scores(competition: str | None = COMP, day: date | None = DAY,
                            ctx: AppState = Depends(get_ctx)):
    comp = competition or ctx.settings.sportsdataio_soccer_competition
    return await _call(ctx.sportsdataio.soccer_box_scores_by_date(comp, day or date.today()))


@router.get("/soccer/box-score/{game_id}", summary="Box score for one game")
async def soccer_box_score(game_id: int = Path(..., description="SportsDataIO GameId"),
                           competition: str | None = COMP, ctx: AppState = Depends(get_ctx)):
    comp = competition or ctx.settings.sportsdataio_soccer_competition
    return await _call(ctx.sportsdataio.soccer_box_score(comp, game_id))


@router.get("/soccer/lineups", summary="Projected/confirmed lineups for a date")
async def soccer_lineups(competition: str | None = COMP, day: date | None = DAY, ctx: AppState = Depends(get_ctx)):
    comp = competition or ctx.settings.sportsdataio_soccer_competition
    return await _call(ctx.sportsdataio.soccer_lineups_by_date(comp, day or date.today()))


@router.get("/soccer/injuries", summary="Injured players")
async def soccer_injuries(competition: str | None = COMP, ctx: AppState = Depends(get_ctx)):
    comp = competition or ctx.settings.sportsdataio_soccer_competition
    return await _call(ctx.sportsdataio.soccer_injuries(comp))


@router.get("/{league}/games", summary="NBA / MLB / NHL games for a date")
async def league_games(league: League, day: date | None = DAY, ctx: AppState = Depends(get_ctx)):
    """Example: `GET /stats/nba/games?day=2026-11-25`"""
    return await _call(ctx.sportsdataio.games_by_date(league.value, day or date.today()))


@router.get("/{league}/injuries", summary="NBA / MLB / NHL injuries")
async def league_injuries(league: League, ctx: AppState = Depends(get_ctx)):
    return await _call(ctx.sportsdataio.injuries(league.value))
