"""Redis client singleton for Personal Model dimension state."""
import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        logger.info("Redis client initialized: %s", REDIS_URL)
    return _redis


async def close() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


# Key helpers — all Personal Model state lives under pm: namespace
def dim_key(dim_id: str) -> str:
    """Current dimension state key."""
    return f"pm:dim:{dim_id}"


def dim_lock_key(dim_id: str) -> str:
    """Update lock key to prevent concurrent writes."""
    return f"pm:lock:{dim_id}"


def event_buffer_key() -> str:
    """Accumulated raw events pending next model update cycle."""
    return "pm:event_buffer"


def cold_start_key() -> str:
    """Cold-start phase tracking (0, 1, 2)."""
    return "pm:cold_start_phase"


def last_updater_run_key() -> str:
    return "pm:last_updater_run"


def last_insight_run_key() -> str:
    return "pm:last_insight_run"
