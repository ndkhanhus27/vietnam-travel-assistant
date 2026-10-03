from __future__ import annotations

import unittest
from unittest.mock import patch

from redis.exceptions import RedisError

from app.api.dependencies import _enforce_rate_limit
from app.core.config import settings


class UnavailableLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self, **kwargs):
        self.calls += 1
        raise RedisError("redis unavailable")


class RedisRegressionTest(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_fails_open_when_redis_is_unavailable(self) -> None:
        limiter = UnavailableLimiter()

        with patch.object(settings, "rate_limit_enabled", True):
            await _enforce_rate_limit(
                limiter=limiter,
                scope="chat",
                identity="test-user",
                limit=10,
                window_seconds=60,
            )

        self.assertEqual(limiter.calls, 1)


if __name__ == "__main__":
    unittest.main()
