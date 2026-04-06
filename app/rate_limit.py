import time
import threading
from collections import defaultdict


class RateLimiter:
    """
    Simple sliding-window rate limiter.
    Thread-safe via a lock; works across async handlers
    since FastAPI runs in a single event loop thread.
    """

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._store: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._store[ip]
            # Evict old entries
            self._store[ip] = [t for t in timestamps if t > cutoff]
            if len(self._store[ip]) >= self.max_requests:
                return False
            self._store[ip].append(now)
            return True