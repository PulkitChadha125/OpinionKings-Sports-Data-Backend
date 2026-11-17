from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OddsPapi
    oddspapi_api_key: str = ""
    oddspapi_base_url: str = "https://v5.oddspapi.io"
    oddspapi_lang: str = "en"
    oddspapi_ws_url: str = "wss://v5.oddspapi.io/ws"
    oddspapi_ws_enabled: bool = True
    oddspapi_ws_channels: str = "fixtures,scores,odds"
    exchanges: str = "kalshi,polymarket,polymarket.us,prophetx,limitless-ex"
    sport_ids: str = "10,11,14"

    # SportsDataIO
    sportsdataio_api_key: str = ""
    sportsdataio_base_url: str = "https://api.sportsdata.io"
    sportsdataio_soccer_competition: str = "3"

    # Backend
    database_url: str = "sqlite+aiosqlite:///./sportdata.db"
    background_jobs_enabled: bool = True
    fixture_sync_interval_sec: int = 600
    activation_interval_sec: int = 300
    activation_window_hours: int = 24
    sync_horizon_days: int = 3

    @property
    def exchange_list(self) -> list[str]:
        return _csv(self.exchanges)

    @property
    def sport_id_list(self) -> list[int]:
        return [int(s) for s in _csv(self.sport_ids)]

    @property
    def ws_channel_list(self) -> list[str]:
        return _csv(self.oddspapi_ws_channels)

    @property
    def ws_filters(self) -> dict:
        """Login-time WebSocket filters. Without them the odds channel streams every bookmaker
        and sport, and the server disconnects us with 4002 backpressure."""
        return {"sportIds": self.sport_id_list, "bookmakers": self.exchange_list}


@lru_cache
def get_settings() -> Settings:
    return Settings()
