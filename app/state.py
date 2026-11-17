from dataclasses import dataclass, field
import asyncio

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.config import Settings
from app.providers.oddspapi import OddsPapiClient
from app.providers.sportsdataio import SportsDataIOClient
from app.services.latency import LatencyTracker
from app.services.live_hub import LiveHub
from app.services.oddspapi_ws import OddsPapiStream


@dataclass
class AppState:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker
    http: httpx.AsyncClient
    tracker: LatencyTracker
    hub: LiveHub
    oddspapi: OddsPapiClient
    sportsdataio: SportsDataIOClient
    stream: OddsPapiStream | None = None
    tasks: list[asyncio.Task] = field(default_factory=list)
