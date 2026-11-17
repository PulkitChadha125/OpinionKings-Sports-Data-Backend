import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """FastAPI TestClient with a throwaway SQLite DB, fake keys and no background jobs."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("BACKGROUND_JOBS_ENABLED", "false")
    monkeypatch.setenv("ODDSPAPI_API_KEY", "test-odds-key")
    monkeypatch.setenv("SPORTSDATAIO_API_KEY", "test-sdio-key")
    monkeypatch.setenv("SPORT_IDS", "10")
    monkeypatch.setenv("EXCHANGES", "kalshi,polymarket")
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()
