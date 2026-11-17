"""In-process pub/sub that fans vendor updates out to our WebSocket clients.

For multiple API instances, swap this for Redis pub/sub - same interface.
"""

import asyncio
from collections import defaultdict
from typing import Any


class LiveHub:
    def __init__(self, queue_size: int = 1000):
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._queue_size = queue_size
        self.latest: dict[str, dict] = {}  # topic -> last message (snapshot for new subscribers)

    def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subs[topic].add(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        self._subs[topic].discard(q)
        if not self._subs[topic]:
            self._subs.pop(topic, None)

    def publish(self, topic: str, message: dict[str, Any]) -> None:
        self.latest[topic] = message
        for t in (topic, "all"):
            for q in list(self._subs.get(t, ())):
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:  # slow consumer: drop oldest
                    try:
                        q.get_nowait()
                        q.put_nowait(message)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass

    @property
    def subscriber_count(self) -> int:
        return sum(len(s) for s in self._subs.values())
