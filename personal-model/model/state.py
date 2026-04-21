"""DimensionState — current dimension state stored in Redis.

Represents the live, hot version of each dimension.
Persisted to PostgreSQL as a snapshot by the Model Updater after each write.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from infra.redis_client import get_redis, dim_key, dim_lock_key

logger = logging.getLogger(__name__)

LOCK_TTL = 30  # seconds


class DimensionState(BaseModel):
    dim_id: str
    current_value: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 3600
    source_events: list[str] = Field(default_factory=list)
    version: int = 1


async def get_state(dim_id: str) -> Optional[DimensionState]:
    redis = await get_redis()
    raw = await redis.get(dim_key(dim_id))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return DimensionState(**data)
    except Exception as exc:
        logger.error("Failed to parse state for %s: %s", dim_id, exc)
        return None


async def set_state(state: DimensionState) -> DimensionState:
    """Write dimension state to Redis.

    Returns a new DimensionState with incremented version and updated timestamp,
    leaving the caller's object unmodified.
    """
    redis = await get_redis()
    written = state.model_copy(update={
        "version": state.version + 1,
        "last_updated": datetime.now(timezone.utc),
    })
    await redis.set(
        dim_key(written.dim_id),
        written.model_dump_json(),
        ex=written.ttl_seconds,
    )
    logger.debug("State written: %s (v%d, confidence=%.2f)", written.dim_id, written.version, written.confidence)

    # Publish dimension update so Arbor Core can fan out to subscribed apps
    try:
        from infra.nats_client import publish
        import json as _json
        await publish(
            f"pm.dimension.updated.{written.dim_id}",
            _json.dumps({
                "dim_id": written.dim_id,
                "current_value": written.current_value,
                "confidence": written.confidence,
                "last_updated": written.last_updated.isoformat(),
                "version": written.version,
            }).encode(),
        )
    except Exception as exc:
        logger.warning("Failed to publish dimension update for %s: %s", written.dim_id, exc)

    return written


async def get_all_states() -> dict[str, Optional[DimensionState]]:
    """Fetch current state for all 20 dimensions."""
    from model.dimensions import ALL_DIMENSIONS
    redis = await get_redis()

    keys = [dim_key(d.id) for d in ALL_DIMENSIONS]
    values = await redis.mget(*keys)

    result: dict[str, Optional[DimensionState]] = {}
    for dim, raw in zip(ALL_DIMENSIONS, values):
        if raw is None:
            result[dim.id] = None
        else:
            try:
                result[dim.id] = DimensionState(**json.loads(raw))
            except Exception:
                result[dim.id] = None
    return result


async def acquire_lock(dim_id: str) -> bool:
    """Optimistic lock before writing a dimension. Returns True if acquired."""
    redis = await get_redis()
    result = await redis.set(dim_lock_key(dim_id), "1", nx=True, ex=LOCK_TTL)
    return result is not None


async def release_lock(dim_id: str) -> None:
    redis = await get_redis()
    await redis.delete(dim_lock_key(dim_id))
