import asyncio
import time
from typing import Any

import httpx

from app.services.latency import LatencyTracker


class ProviderError(Exception):
    def __init__(self, provider: str, status: int | None, message: str, url: str = ""):
        super().__init__(f"[{provider}] {status}: {message} ({url})")
        self.provider = provider
        self.status = status
        self.message = message
        self.url = url


class MissingCredentials(ProviderError):
    def __init__(self, provider: str):
        super().__init__(provider, None, "API key not configured - set it in .env")


class BaseHTTPProvider:
    name = "base"
    max_retries = 2

    def __init__(self, client: httpx.AsyncClient, tracker: LatencyTracker, api_key: str):
        self.client = client
        self.tracker = tracker
        self.api_key = api_key

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _auth_headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def _get(self, url: str, params: dict[str, Any] | None = None, kind: str = "rest") -> Any:
        if not self.configured:
            raise MissingCredentials(self.name)
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                resp = await self.client.get(url, params=clean, headers=self._auth_headers(), timeout=20)
            except httpx.HTTPError as exc:
                self.tracker.record(self.name, kind, None, ok=False)
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise ProviderError(self.name, None, f"network error: {exc}", url) from exc
            elapsed_ms = (time.perf_counter() - started) * 1000

            if resp.status_code == 429 and attempt < self.max_retries:
                self.tracker.record(self.name, kind, None, ok=False)
                await asyncio.sleep(float(resp.headers.get("Retry-After", "1")))
                continue
            if resp.status_code >= 400:
                self.tracker.record(self.name, kind, None, ok=False)
                raise ProviderError(self.name, resp.status_code, resp.text[:500], str(resp.request.url))

            self.tracker.record(self.name, kind, elapsed_ms)
            if not resp.content:
                return None
            try:
                return resp.json()
            except ValueError:
                return resp.text
        raise ProviderError(self.name, 429, "rate limited after retries", url)
