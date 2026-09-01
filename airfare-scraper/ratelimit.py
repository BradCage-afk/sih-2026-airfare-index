"""A blocking sliding-window rate limiter.

NIM's free tier allows ~40 requests/minute across whichever model is active,
so every extractor call goes through one shared instance.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, per_minute: int, window_s: float = 60.0):
        self.per_minute = max(1, per_minute)
        self.window_s = window_s
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a slot is free. Returns seconds spent waiting."""
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                while self._hits and now - self._hits[0] >= self.window_s:
                    self._hits.popleft()
                if len(self._hits) < self.per_minute:
                    self._hits.append(now)
                    return waited
                sleep_for = self.window_s - (now - self._hits[0]) + 0.01
            time.sleep(sleep_for)
            waited += sleep_for

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        return False
