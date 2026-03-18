"""Token bucket rate limiter for controlling API call frequency."""

from __future__ import annotations

import threading
import time


class TokenBucketLimiter:
    """Thread-safe token bucket rate limiter.

    Allows up to `capacity` tokens to accumulate. Tokens refill at `rate` per second.
    Calling acquire() blocks until a token is available.
    """

    def __init__(self, rate: float = 0.5, capacity: int = 1) -> None:
        """
        Args:
            rate: Tokens added per second (default 0.5 = one request every 2 seconds).
            capacity: Maximum tokens in the bucket (default 1).
        """
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_time = (1.0 - self._tokens) / self._rate
            time.sleep(wait_time)

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill (call with lock held)."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now
