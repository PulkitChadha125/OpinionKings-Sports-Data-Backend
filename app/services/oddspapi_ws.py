"""OddsPapi v5 WebSocket consumer.

Protocol (docs.oddspapi.io/websocket):
  -> {"type": "login", "apiKey": ..., "channels": [...], "receiveType": "json",
      "serverEpoch": ..., "lastSeenId": {channel: entryId}}   (resume fields optional)
  <- control: login_ok | snapshot_required | resume_complete | reconnect
  <- data:    {"channel", "type": "UPDATE", "payload", "ts", "entryId"}
Subscriptions are login-only: to change channels/filters, reconnect.
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

import websockets

from app.services.latency import LatencyTracker
from app.services.live_hub import LiveHub

log = logging.getLogger(__name__)

CONTROL_TYPES = {"login_ok", "snapshot_required", "resume_complete", "reconnect", "error"}


class OddsPapiStream:
    def __init__(self, url: str, api_key: str, channels: list[str], tracker: LatencyTracker,
                 hub: LiveHub, filters: dict[str, Any] | None = None,
                 on_fixture_update: Callable[[dict], Awaitable[None]] | None = None,
                 on_snapshot_required: Callable[[list[str]], Awaitable[None]] | None = None):
        self.url = url
        self.api_key = api_key
        self.channels = channels
        self.filters = filters or {}
        self.tracker = tracker
        self.hub = hub
        self.on_fixture_update = on_fixture_update
        self.on_snapshot_required = on_snapshot_required

        self.server_epoch: str | None = None
        self.cursors: dict[str, str] = {}
        self.connected = False
        self.message_counts: dict[str, int] = {}
        self.last_error: str | None = None
        self.last_login_ok: dict | None = None

    def login_message(self) -> dict:
        msg: dict[str, Any] = {"type": "login", "apiKey": self.api_key, "channels": self.channels,
                               "receiveType": "json", **self.filters}
        if self.server_epoch and self.cursors:
            msg["serverEpoch"] = self.server_epoch
            msg["lastSeenId"] = self.cursors
        return msg

    async def run(self, stop_after: float | None = None) -> None:
        """Run forever with reconnect/backoff (or for `stop_after` seconds, for tests)."""
        deadline = time.monotonic() + stop_after if stop_after else None
        backoff = 1.0
        while deadline is None or time.monotonic() < deadline:
            try:
                await self._session(deadline)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("oddspapi ws error: %s (retry in %.0fs)", self.last_error, backoff)
                self.tracker.record("oddspapi", "ws:connection", None, ok=False)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                self.connected = False

    async def _session(self, deadline: float | None) -> None:
        async with websockets.connect(self.url, max_size=None, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps(self.login_message()))
            self.connected = True
            log.info("oddspapi ws connected, channels=%s", self.channels)
            while True:
                timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
                if timeout == 0.0:
                    return
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    return
                if await self.handle_raw(raw) == "reconnect":
                    return

    async def handle_raw(self, raw: str | bytes) -> str | None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            log.debug("non-json frame ignored (%d bytes)", len(raw))
            return None
        if not isinstance(msg, dict):
            return None

        mtype = msg.get("type")
        if mtype in CONTROL_TYPES and "channel" not in msg:
            return await self._handle_control(msg)

        channel = msg.get("channel", "unknown")
        self.message_counts[channel] = self.message_counts.get(channel, 0) + 1
        if msg.get("entryId"):
            self.cursors[channel] = msg["entryId"]
        ts = msg.get("ts")
        delay = (time.time() * 1000 - ts) if isinstance(ts, (int, float)) else None
        self.tracker.record("oddspapi", f"ws:{channel}", delay)

        payload = msg.get("payload") or {}
        fixture_id = payload.get("fixtureId") if isinstance(payload, dict) else None
        out = {"type": channel, "fixtureId": fixture_id, "ts": ts, "payload": payload}
        self.hub.publish(f"fixture:{fixture_id}" if fixture_id else f"channel:{channel}", out)

        if channel in ("fixtures", "scores") and fixture_id and self.on_fixture_update:
            try:
                await self.on_fixture_update({"channel": channel, **payload})
            except Exception:
                log.exception("fixture update handler failed")
        return None

    async def _handle_control(self, msg: dict) -> str | None:
        mtype = msg["type"]
        log.info("oddspapi ws control: %s", msg)
        if mtype == "login_ok":
            self.last_login_ok = msg
            resume = msg.get("resume") or {}
            new_epoch = resume.get("serverEpoch") or msg.get("serverEpoch")
            if new_epoch and self.server_epoch and new_epoch != self.server_epoch:
                self.cursors.clear()  # server restarted: cursors invalid
                if self.on_snapshot_required:
                    await self.on_snapshot_required(self.channels)
            self.server_epoch = new_epoch or self.server_epoch
        elif mtype == "snapshot_required":
            for ch in msg.get("channels", []):
                self.cursors.pop(ch, None)
            if self.on_snapshot_required:
                await self.on_snapshot_required(msg.get("channels", []))
        elif mtype == "reconnect":
            return "reconnect"
        elif mtype == "error":
            self.last_error = json.dumps(msg)
        return None

    def status(self) -> dict:
        return {"connected": self.connected, "channels": self.channels, "serverEpoch": self.server_epoch,
                "messages": self.message_counts, "lastError": self.last_error}
