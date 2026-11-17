from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_ctx
from app.models import Fixture, as_utc
from app.state import AppState
from app.api import tags

router = APIRouter(prefix="/fixtures", tags=[tags.BACKEND_FIXTURES])


class MarketOut(BaseModel):
    exchange: str
    exchange_fixture_id: str | None
    market_count: int
    last_seen: datetime | None


class FixtureOut(BaseModel):
    id: int
    oddspapi_id: str | None
    sportsdataio_id: str | None
    sport_id: int | None
    sport_name: str | None
    tournament_name: str | None
    home: str
    away: str
    start_time: datetime
    lifecycle: str
    vendor_status_id: int | None
    reschedule_count: int
    home_score: int | None
    away_score: int | None
    activated_at: datetime | None
    markets: list[MarketOut] = []


class EventOut(BaseModel):
    from_state: str | None
    to_state: str
    reason: str
    at: datetime


class FixtureDetail(FixtureOut):
    scores: dict | None = None
    events: list[EventOut] = []


def _out(fx: Fixture, detail: bool = False) -> dict:
    data = {c: getattr(fx, c) for c in FixtureOut.model_fields if c != "markets"}
    data["start_time"] = as_utc(fx.start_time)
    data["activated_at"] = as_utc(fx.activated_at)
    data["markets"] = [MarketOut(exchange=m.exchange, exchange_fixture_id=m.exchange_fixture_id,
                                 market_count=m.market_count, last_seen=as_utc(m.last_seen)) for m in fx.markets]
    if detail:
        data["scores"] = fx.scores
        data["events"] = [EventOut(from_state=e.from_state, to_state=e.to_state, reason=e.reason,
                                   at=as_utc(e.at)) for e in sorted(fx.events, key=lambda e: e.at)]
    return data


@router.get("", response_model=list[FixtureOut])
async def list_fixtures(lifecycle: str | None = None, sport_id: int | None = None, limit: int = 200,
                        ctx: AppState = Depends(get_ctx)):
    q = select(Fixture).options(selectinload(Fixture.markets)).order_by(Fixture.start_time).limit(limit)
    if lifecycle:
        q = q.where(Fixture.lifecycle == lifecycle.upper())
    if sport_id is not None:
        q = q.where(Fixture.sport_id == sport_id)
    async with ctx.session_factory() as session:
        return [_out(fx) for fx in (await session.execute(q)).scalars().all()]


@router.get("/{fixture_id}", response_model=FixtureDetail)
async def get_fixture(fixture_id: str, ctx: AppState = Depends(get_ctx)):
    """Lookup by internal id or OddsPapi fixture id."""
    cond = Fixture.id == int(fixture_id) if fixture_id.isdigit() else Fixture.oddspapi_id == fixture_id
    q = select(Fixture).options(selectinload(Fixture.markets), selectinload(Fixture.events)).where(cond)
    async with ctx.session_factory() as session:
        fx = (await session.execute(q)).scalar_one_or_none()
    if fx is None:
        raise HTTPException(404, "fixture not found")
    return _out(fx, detail=True)
