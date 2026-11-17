from datetime import date

from fastapi import APIRouter, Depends

from app.api.deps import get_ctx, provider_http_error
from app.providers.base import ProviderError
from app.services import jobs
from app.state import AppState
from app.api import tags

router = APIRouter(prefix="/admin", tags=[tags.BACKEND_ADMIN])


@router.post("/sync-fixtures")
async def sync_fixtures(ctx: AppState = Depends(get_ctx)):
    try:
        return await jobs.sync_fixtures(ctx.session_factory, ctx.oddspapi, ctx.settings, ctx.hub)
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.post("/activate-markets")
async def activate_markets(ctx: AppState = Depends(get_ctx)):
    try:
        return await jobs.activate_markets(ctx.session_factory, ctx.oddspapi, ctx.settings, ctx.hub)
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.post("/link-sportsdataio")
async def link_sportsdataio(day: date | None = None, ctx: AppState = Depends(get_ctx)):
    try:
        return await jobs.link_sportsdataio_soccer(ctx.session_factory, ctx.sportsdataio, ctx.settings, day)
    except ProviderError as exc:
        raise provider_http_error(exc)
