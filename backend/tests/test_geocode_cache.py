import asyncio
import unittest

import httpx
from redis.exceptions import RedisError

from app.infra.redis import RedisJsonCache, ThreadJsonCache
from pipeline.agents.tools.providers.goong import GoongClient


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttl = None
        self.unavailable = False

    async def get(self, key):
        if self.unavailable:
            raise RedisError("offline")
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        if self.unavailable:
            raise RedisError("offline")
        self.values[key] = value
        self.ttl = ex


class GeocodeCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_workers_share_geocode_cache_and_refresh_after_expiry(self):
        redis = FakeRedis()
        cache = ThreadJsonCache(RedisJsonCache(redis), asyncio.get_running_loop())
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"results": [{"geometry": {"location": {"lat": 16.4, "lng": 107.6}}}]})

        with httpx.Client(transport=httpx.MockTransport(respond)) as http:
            client = GoongClient(api_key="test", http_client=http, cache=cache)
            first = await asyncio.to_thread(client.geocode, "Huế")
            second = await asyncio.to_thread(client.geocode, "  HUẾ  ")
            self.assertEqual(first, second)
            self.assertEqual(len(requests), 1)
            self.assertEqual(redis.ttl, 86400)
            redis.values.clear()
            await asyncio.to_thread(client.geocode, "Huế")
            self.assertEqual(len(requests), 2)
            redis.unavailable = True
            await asyncio.to_thread(client.geocode, "Huế")
            self.assertEqual(len(requests), 3)

    async def test_empty_provider_result_is_not_cached(self):
        redis = FakeRedis()
        cache = ThreadJsonCache(RedisJsonCache(redis), asyncio.get_running_loop())
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))) as http:
            client = GoongClient(api_key="test", http_client=http, cache=cache)
            await asyncio.to_thread(client.geocode, "unknown")
        self.assertEqual(redis.values, {})
