"""In-memory latency/staleness tracker used to compare vendors during the trial.

REST: round-trip time of each request.
WebSocket: now - vendor timestamp (`ts`) of each message, i.e. delivery delay.
"""

import time
from collections import defaultdict, deque


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[idx], 1)


class LatencyTracker:
    def __init__(self, window: int = 5000):
        self._window: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=window))
        self._pending: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._errors: dict[tuple[str, str], int] = defaultdict(int)
        self._pending_errors: dict[tuple[str, str], int] = defaultdict(int)
        self.last_seen: dict[str, float] = {}  # "provider:kind" -> unix time

    def record(self, provider: str, kind: str, latency_ms: float | None, ok: bool = True) -> None:
        key = (provider, kind)
        self.last_seen[f"{provider}:{kind}"] = time.time()
        if not ok:
            self._errors[key] += 1
            self._pending_errors[key] += 1
            return
        if latency_ms is not None:
            self._window[key].append(latency_ms)
            self._pending[key].append(latency_ms)

    def stats(self) -> list[dict]:
        keys = set(self._window) | set(self._errors)
        out = []
        now = time.time()
        for provider, kind in sorted(keys):
            vals = list(self._window[(provider, kind)])
            last = self.last_seen.get(f"{provider}:{kind}")
            out.append(
                {
                    "provider": provider,
                    "kind": kind,
                    "samples": len(vals),
                    "errors": self._errors[(provider, kind)],
                    "p50_ms": percentile(vals, 50),
                    "p95_ms": percentile(vals, 95),
                    "max_ms": round(max(vals), 1) if vals else 0.0,
                    "seconds_since_last": round(now - last, 1) if last else None,
                }
            )
        return out

    def drain(self) -> list[dict]:
        """Return aggregates since the last drain (for persisting) and reset them."""
        keys = set(self._pending) | set(self._pending_errors)
        rows = []
        for provider, kind in keys:
            vals = self._pending.get((provider, kind), [])
            errs = self._pending_errors.get((provider, kind), 0)
            if not vals and not errs:
                continue
            rows.append(
                {
                    "provider": provider,
                    "kind": kind,
                    "count": len(vals),
                    "errors": errs,
                    "p50_ms": percentile(vals, 50),
                    "p95_ms": percentile(vals, 95),
                    "max_ms": round(max(vals), 1) if vals else 0.0,
                }
            )
        self._pending.clear()
        self._pending_errors.clear()
        return rows
