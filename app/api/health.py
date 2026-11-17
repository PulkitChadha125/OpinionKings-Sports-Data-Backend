from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import get_ctx
from app.models import LatencySummary
from app.state import AppState

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(ctx: AppState = Depends(get_ctx)):
    return {
        "status": "ok",
        "providers": {
            "oddspapi": {"configured": ctx.oddspapi.configured,
                         "websocket": ctx.stream.status() if ctx.stream else None},
            "sportsdataio": {"configured": ctx.sportsdataio.configured},
        },
        "live_subscribers": ctx.hub.subscriber_count,
    }


@router.get("/metrics/latency")
async def latency(ctx: AppState = Depends(get_ctx)):
    """Live latency/staleness per provider and endpoint (rolling window)."""
    return ctx.tracker.stats()


@router.get("/metrics/latency/history")
async def latency_history(provider: str | None = None, limit: int = 500, ctx: AppState = Depends(get_ctx)):
    """Persisted per-minute aggregates - the raw material for the vendor comparison report."""
    q = select(LatencySummary).order_by(LatencySummary.at.desc()).limit(limit)
    if provider:
        q = q.where(LatencySummary.provider == provider)
    async with ctx.session_factory() as session:
        rows = (await session.execute(q)).scalars().all()
    return [{"provider": r.provider, "kind": r.kind, "count": r.count, "errors": r.errors,
             "p50_ms": r.p50_ms, "p95_ms": r.p95_ms, "max_ms": r.max_ms, "at": r.at} for r in rows]
