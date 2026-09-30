from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from redis.asyncio import Redis
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)

KEY_PREFIX = "vta"
_SAFE_SCOPE = re.compile(r"[^a-z0-9_-]+")
_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""
_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


def normalize_cache_part(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def _scope(value: str) -> str:
    normalized = _SAFE_SCOPE.sub("-", value.strip().casefold()).strip("-")
    if not normalized:
        raise ValueError("Redis key scope must not be empty")
    return normalized


def _digest(parts: Sequence[object]) -> str:
    normalized = "\x1f".join(normalize_cache_part(part) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def rate_limit_key(scope: str, identity: object, window_bucket: int) -> str:
    return (
        f"{KEY_PREFIX}:ratelimit:{_scope(scope)}:"
        f"{_digest([identity])}:{window_bucket}"
    )


def cache_key(scope: str, *parts: object) -> str:
    if not parts:
        raise ValueError("Cache key requires at least one value")
    return f"{KEY_PREFIX}:cache:{_scope(scope)}:{_digest(parts)}"


def lock_key(scope: str, *parts: object) -> str:
    if not parts:
        raise ValueError("Lock key requires at least one value")
    return f"{KEY_PREFIX}:lock:{_scope(scope)}:{_digest(parts)}"


async def create_redis_client(
    url: str,
    *,
    connect_timeout_seconds: float,
) -> Redis:
    client = Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=connect_timeout_seconds,
        socket_timeout=connect_timeout_seconds,
    )
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        raise
    return client


class RedisRateLimiter:
    def __init__(
        self,
        client: Any,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.clock = clock

    async def check(
        self,
        *,
        scope: str,
        identity: object,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("Rate limit and window must be positive")

        now = self.clock()
        bucket = int(now // window_seconds)
        key = rate_limit_key(scope, identity, bucket)
        count, ttl = await self.client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            key,
            window_seconds,
        )
        count = int(count)
        ttl = int(ttl)
        retry_after = max(ttl, 1) if count > limit else 0
        return RateLimitResult(
            allowed=count <= limit,
            remaining=max(limit - count, 0),
            retry_after=retry_after,
        )


class RedisJsonCache:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def get_json(self, key: str) -> JsonValue | None:
        try:
            payload = await self.client.get(key)
            if payload is None:
                logger.debug("Redis cache miss")
                return None
            logger.debug("Redis cache hit")
            return json.loads(payload)
        except (RedisError, OSError) as exc:
            logger.warning("Redis cache read unavailable: %s", type(exc).__name__)
            return None

    async def set_json(
        self,
        key: str,
        value: JsonValue,
        *,
        ttl_seconds: int,
    ) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("Cache TTL must be positive")
        try:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            await self.client.set(key, payload, ex=ttl_seconds)
            return True
        except (TypeError, ValueError):
            raise
        except (RedisError, OSError) as exc:
            logger.warning("Redis cache write unavailable: %s", type(exc).__name__)
            return False

    async def delete(self, key: str) -> bool:
        try:
            return bool(await self.client.delete(key))
        except (RedisError, OSError) as exc:
            logger.warning("Redis cache delete unavailable: %s", type(exc).__name__)
            return False

    async def get_or_set(
        self,
        key: str,
        provider: Callable[[], Awaitable[T]],
        *,
        ttl_seconds: int,
    ) -> T:
        cached = await self.get_json(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        value = await provider()
        await self.set_json(key, value, ttl_seconds=ttl_seconds)  # type: ignore[arg-type]
        return value


class RedisLockManager:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def acquire(self, key: str, *, ttl_seconds: int) -> str | None:
        if ttl_seconds <= 0:
            raise ValueError("Lock TTL must be positive")
        token = uuid.uuid4().hex
        acquired = await self.client.set(key, token, ex=ttl_seconds, nx=True)
        return token if acquired else None

    async def release(self, key: str, token: str) -> bool:
        released = await self.client.eval(
            _RELEASE_LOCK_SCRIPT,
            1,
            key,
            token,
        )
        return bool(released)
