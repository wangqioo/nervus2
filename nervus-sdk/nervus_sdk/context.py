"""Context — Redis-backed user context graph for nervus2 apps."""
import json
import logging
import os
from typing import Any, Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# Default TTL by context key prefix (seconds)
_TTL_MAP = {
    "temporal.": 6 * 3600,
    "physical.": 24 * 3600,
    "cognitive.": 12 * 3600,
    "social.": 12 * 3600,
    "travel.": 7 * 24 * 3600,
    "app.": None,              # no expiry
}


class Context:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    async def get(self, field: str) -> Optional[Any]:
        redis = await self._get_redis()
        raw = await redis.get(f"context:user:{field}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    async def set(self, field: str, value: Any, ttl: Optional[int] = None) -> None:
        redis = await self._get_redis()
        if ttl is None:
            ttl = self._default_ttl(field)
        raw = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            await redis.set(f"context:user:{field}", raw, ex=ttl)
        else:
            await redis.set(f"context:user:{field}", raw)

    async def delete(self, field: str) -> None:
        redis = await self._get_redis()
        await redis.delete(f"context:user:{field}")

    async def get_many(self, fields: list[str]) -> dict[str, Any]:
        redis = await self._get_redis()
        keys = [f"context:user:{f}" for f in fields]
        values = await redis.mget(*keys)
        result = {}
        for field, raw in zip(fields, values):
            if raw is not None:
                try:
                    result[field] = json.loads(raw)
                except Exception:
                    result[field] = raw
        return result

    @staticmethod
    def _default_ttl(field: str) -> Optional[int]:
        for prefix, ttl in _TTL_MAP.items():
            if field.startswith(prefix):
                return ttl
        return 3600  # default 1h
