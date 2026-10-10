"""Run against disposable CI services; never modify production collections."""
import asyncio
import os
import unittest
import uuid

from redis.asyncio import Redis
from qdrant_client import QdrantClient, models
from app.infra.redis import RedisJsonCache, RedisRateLimiter, cache_key, rate_limit_key


@unittest.skipUnless(os.getenv("TEST_REDIS_URL"), "TEST_REDIS_URL is not configured")
class LiveRedisTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_rate_limit_and_cache_expiry(self):
        client = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
        scope = "test-" + uuid.uuid4().hex
        now = 1000.0
        key = cache_key(scope, "sample")
        limit_key = rate_limit_key(scope, "user", int(now // 60))
        try:
            limiter = RedisRateLimiter(client, clock=lambda: now)
            results = await asyncio.gather(*(limiter.check(scope=scope, identity="user", limit=3, window_seconds=60) for _ in range(8)))
            self.assertEqual(sum(result.allowed for result in results), 3)
            self.assertTrue(all(result.retry_after > 0 for result in results if not result.allowed))
            cache = RedisJsonCache(client)
            await cache.set_json(key, {"value": "Da Lat"}, ttl_seconds=1)
            self.assertEqual(await cache.get_json(key), {"value": "Da Lat"})
            await asyncio.sleep(1.1)
            self.assertIsNone(await cache.get_json(key))
        finally:
            await client.delete(key, limit_key)
            await client.aclose()


@unittest.skipUnless(os.getenv("TEST_QDRANT_URL"), "TEST_QDRANT_URL is not configured")
class LiveQdrantTest(unittest.TestCase):
    def test_upsert_and_retrieve_known_nearest_point(self):
        client = QdrantClient(url=os.environ["TEST_QDRANT_URL"])
        collection = "regression_" + uuid.uuid4().hex
        created = False
        try:
            client.create_collection(collection, vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE))
            created = True
            client.upsert(collection, points=[models.PointStruct(id=1, vector=[1., 0., 0., 0.], payload={"text": "Da Lat"}), models.PointStruct(id=2, vector=[0., 1., 0., 0.], payload={"text": "Ha Noi"})], wait=True)
            result = client.query_points(collection, query=[1., 0., 0., 0.], limit=1, with_payload=True)
            self.assertEqual(result.points[0].payload["text"], "Da Lat")
            self.assertEqual(client.count(collection, exact=True).count, 2)
        finally:
            if created:
                client.delete_collection(collection)
            client.close()
