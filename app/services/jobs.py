"""Background jobs: fixture sync, market activation, SportsDataIO linking, latency flush."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import (ExchangeMarket, Fixture, LatencySummary, Lifecycle, LifecycleEvent, as_utc,
                        utcnow)
from app.providers.base import ProviderError
from app.providers.oddspapi import OddsPapiClient
from app.providers.sportsdataio import SportsDataIOClient
from app.services.latency import LatencyTracker
from app.services.lifecycle import activation_transition, vendor_transition
from app.services.live_hub import LiveHub
from app.services.mapping import best_match, discover_exchange_markets
from app.services.normalize import as_list, parse_oddspapi_fixture, parse_sportsdataio_soccer_game

log = logging.getLogger(__name__)


def set_state(session: AsyncSession, fx: Fixture, new: Lifecycle, reason: str, hub: LiveHub | None) -> None:
    old = fx.lifecycle
    fx.lifecycle = new.value
    if new == Lifecycle.ACTIVE and fx.activated_at is None:
        fx.activated_at = utcnow()
    # fixture_id (not relationship) avoids an implicit lazy-load of fx.events under asyncio
    session.add(LifecycleEvent(fixture_id=fx.id, from_state=old, to_state=new.value, reason=reason))
    log.info("fixture %s %s -> %s (%s)", fx.oddspapi_id, old, new.value, reason)
    if hub and fx.oddspapi_id:
        hub.publish(f"fixture:{fx.oddspapi_id}", {"type": "lifecycle", "fixtureId": fx.oddspapi_id,
                                                 "from": old, "to": new.value, "reason": reason})


async def upsert_fixture(session: AsyncSession, parsed: dict, settings: Settings,
                         hub: LiveHub | None = None) -> Fixture:
    """Insert or update a fixture from a parsed OddsPapi payload and apply lifecycle rules."""
    fx = (await session.execute(
        select(Fixture).where(Fixture.oddspapi_id == parsed["oddspapi_id"]))).scalar_one_or_none()
    now = utcnow()
    window = timedelta(hours=settings.activation_window_hours)

    if fx is None:
        fx = Fixture(**{k: v for k, v in parsed.items()}, lifecycle=Lifecycle.SCHEDULED.value,
                     original_start_time=parsed["start_time"])
        session.add(fx)
        await session.flush()
        transition = vendor_transition(Lifecycle.SCHEDULED, parsed["vendor_status_id"], None,
                                       parsed["start_time"], now, window)
        if transition:
            set_state(session, fx, *transition, hub)
        return fx

    old_start = as_utc(fx.start_time)
    transition = vendor_transition(Lifecycle(fx.lifecycle), parsed["vendor_status_id"], old_start,
                                   parsed["start_time"], now, window)
    if old_start and abs(parsed["start_time"] - old_start) > timedelta(minutes=5):
        fx.reschedule_count = (fx.reschedule_count or 0) + 1
    for key, value in parsed.items():
        if key in ("scores", "home_score", "away_score") and value is None:
            continue  # don't wipe live scores with an empty REST snapshot
        setattr(fx, key, value)
    if transition:
        set_state(session, fx, *transition, hub)
    return fx


async def sync_fixtures(session_factory: async_sessionmaker, odds: OddsPapiClient, settings: Settings,
                        hub: LiveHub | None = None) -> dict:
    """Pull upcoming + live fixtures for configured sports from OddsPapi."""
    horizon = utcnow() + timedelta(days=settings.sync_horizon_days)
    stats = {"seen": 0, "upserted": 0, "errors": []}
    for sport_id in settings.sport_id_list:
        try:
            raw = as_list(await odds.fixtures(sport_id=sport_id, bookmakers=settings.exchange_list))
        except ProviderError as exc:
            stats["errors"].append(str(exc))
            continue
        async with session_factory() as session:
            for item in raw:
                stats["seen"] += 1
                parsed = parse_oddspapi_fixture(item)
                if not parsed or parsed["start_time"] > horizon:
                    continue
                await upsert_fixture(session, parsed, settings, hub)
                stats["upserted"] += 1
            await session.commit()
    return stats


async def activate_markets(session_factory: async_sessionmaker, odds: OddsPapiClient, settings: Settings,
                           hub: LiveHub | None = None) -> dict:
    """Activate fixtures starting within the window that have exchange contracts."""
    now = utcnow()
    window = timedelta(hours=settings.activation_window_hours)
    stats = {"checked": 0, "activated": 0, "pending_mapping": 0, "errors": []}
    async with session_factory() as session:
        candidates = (await session.execute(
            select(Fixture).options(selectinload(Fixture.markets)).where(
                Fixture.lifecycle.in_([Lifecycle.SCHEDULED.value, Lifecycle.POSTPONED.value,
                                       Lifecycle.PENDING_MAPPING.value]),
                Fixture.start_time >= now, Fixture.start_time <= now + window))).scalars().all()

        for fx in candidates:
            stats["checked"] += 1
            try:
                found = await discover_exchange_markets(odds, fx.oddspapi_id, settings.exchange_list)
            except ProviderError as exc:
                stats["errors"].append(str(exc))
                continue
            existing = {m.exchange: m for m in fx.markets}
            for exchange, info in found.items():
                m = existing.get(exchange) or ExchangeMarket(fixture=fx, exchange=exchange)
                m.market_count = info["market_count"]
                m.exchange_fixture_id = info["exchange_fixture_id"] or m.exchange_fixture_id
                m.raw = info["raw"]
                m.last_seen = now
                session.add(m)
            transition = activation_transition(Lifecycle(fx.lifecycle), as_utc(fx.start_time), now, window,
                                               has_markets=bool(found))
            if transition:
                set_state(session, fx, *transition, hub)
                if transition[0] == Lifecycle.ACTIVE:
                    stats["activated"] += 1
                else:
                    stats["pending_mapping"] += 1
            await asyncio.sleep(0.15)  # stay under the 10 req/s odds limit
        await session.commit()
    return stats


async def link_sportsdataio_soccer(session_factory: async_sessionmaker, sdio: SportsDataIOClient,
                                   settings: Settings, day=None) -> dict:
    """Fuzzy-link SportsDataIO soccer games (for stats/lineups) to our OddsPapi fixtures."""
    day = day or utcnow().date()
    games = [g for g in (parse_sportsdataio_soccer_game(r) for r in as_list(
        await sdio.soccer_games_by_date(settings.sportsdataio_soccer_competition, day))) if g]
    linked = []
    async with session_factory() as session:
        fixtures = (await session.execute(select(Fixture).where(
            Fixture.sportsdataio_id.is_(None), Fixture.sport_id == 10))).scalars().all()
        for fx in fixtures:
            target = {"home": fx.home, "away": fx.away, "start_time": as_utc(fx.start_time)}
            match, score = best_match(target, games)
            if match:
                fx.sportsdataio_id = match["sportsdataio_id"]
                linked.append({"fixture": fx.oddspapi_id, "sportsdataio": match["sportsdataio_id"],
                               "score": score})
        await session.commit()
    return {"games": len(games), "linked": linked}


async def flush_latency(session_factory: async_sessionmaker, tracker: LatencyTracker) -> int:
    rows = tracker.drain()
    if not rows:
        return 0
    async with session_factory() as session:
        session.add_all(LatencySummary(**r) for r in rows)
        await session.commit()
    return len(rows)


async def run_periodic(name: str, interval: float, fn, *args) -> None:
    while True:
        try:
            result = await fn(*args)
            log.info("job %s: %s", name, result)
        except asyncio.CancelledError:
            raise
        except Exception:  # keep the loop alive
            log.exception("job %s failed", name)
        await asyncio.sleep(interval)
