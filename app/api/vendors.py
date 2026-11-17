"""Read-only vendor passthrough for exploring the APIs during the trial.

GET /vendors/oddspapi/fixtures?sportId=10      -> https://v5.oddspapi.io/en/fixtures?sportId=10
GET /vendors/sportsdataio/v4/soccer/scores/json/Competitions
Keys are added server-side and never exposed. Disable in production.
"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_ctx, provider_http_error
from app.providers.base import ProviderError
from app.state import AppState

router = APIRouter(prefix="/vendors", tags=["vendor passthrough (trial only)"])


@router.get("/oddspapi/{path:path}")
async def oddspapi(path: str, request: Request, ctx: AppState = Depends(get_ctx)):
    try:
        return await ctx.oddspapi.get(path, dict(request.query_params))
    except ProviderError as exc:
        raise provider_http_error(exc)


@router.get("/sportsdataio/{path:path}")
async def sportsdataio(path: str, request: Request, ctx: AppState = Depends(get_ctx)):
    try:
        return await ctx.sportsdataio.get(path, dict(request.query_params))
    except ProviderError as exc:
        raise provider_http_error(exc)
