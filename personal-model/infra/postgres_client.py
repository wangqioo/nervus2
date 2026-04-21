"""PostgreSQL + pgvector client singleton for Personal Model snapshots and insights."""
import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://nervus:nervus@localhost:5432/nervus2",
)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            POSTGRES_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        # Register pgvector codec so vector columns are returned as list[float]
        async with _pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.set_type_codec(
                "vector",
                encoder=_encode_vector,
                decoder=_decode_vector,
                schema="pg_catalog",
                format="text",
            )
        logger.info("PostgreSQL pool created: %s", POSTGRES_URL)
    return _pool


async def close() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _encode_vector(value: list[float]) -> str:
    return "[" + ",".join(str(v) for v in value) + "]"


def _decode_vector(value: str) -> list[float]:
    return [float(x) for x in value.strip("[]").split(",")]
