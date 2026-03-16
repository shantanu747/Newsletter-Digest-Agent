"""Tests for agent/utils/rate_limiter.py"""

import threading
import time
from unittest.mock import patch

import pytest

from agent.utils.rate_limiter import TokenBucketLimiter


class TestTokenBucketLimiter:
    def test_acquire_returns_immediately_when_token_available(self):
        limiter = TokenBucketLimiter(rate=1.0, capacity=1)
        start = time.monotonic()
        limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # should be near-instant

    def test_acquire_blocks_when_bucket_empty(self):
        """After consuming the first token, the second acquire should block."""
        limiter = TokenBucketLimiter(rate=0.5, capacity=1)
        limiter.acquire()  # consume the one token
        start = time.monotonic()
        # With rate=0.5, refilling 1 token takes 2s — use mock to speed up
        with patch("time.sleep") as mock_sleep:
            # Manually add a token after first sleep call
            def add_token(_):
                limiter._tokens = 1.0
            mock_sleep.side_effect = add_token
            limiter.acquire()
        assert mock_sleep.called

    def test_tokens_do_not_exceed_capacity(self):
        limiter = TokenBucketLimiter(rate=10.0, capacity=2)
        time.sleep(1.0)  # let tokens accumulate
        with limiter._lock:
            limiter._refill()
        assert limiter._tokens <= limiter._capacity

    def test_thread_safety(self):
        """Multiple threads acquiring concurrently should not raise."""
        limiter = TokenBucketLimiter(rate=100.0, capacity=10)
        errors = []

        def worker():
            try:
                limiter.acquire()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        assert not errors
