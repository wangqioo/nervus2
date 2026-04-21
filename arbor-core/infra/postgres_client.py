import logging, os
from typing import Optional
import asyncpg

logger = logging.getLogger(__name__)
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://nervus:nervus@postgres:5432/nervus2")
_pool: Optional[asyncpg.Pool] = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=8)
        logger.info("PostgreSQL pool created")
    return _pool

async def close() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
