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

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = [t for t in self._store[key] if t > cutoff]
            self._store[key] = timestamps
            return max(0, self.max_requests - len(timestamps))

    def retry_after_seconds(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = [t for t in self._store[key] if t > cutoff]
            self._store[key] = timestamps
            if len(timestamps) < self.max_requests:
                return 0
            oldest = min(timestamps)
            return max(1, int((oldest + self.window_seconds) - now))