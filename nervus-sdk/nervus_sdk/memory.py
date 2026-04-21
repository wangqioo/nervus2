"""MemoryGraph — PostgreSQL + pgvector long-term memory for nervus2 apps."""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import asyncpg

logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://nervus:nervus@postgres:5432/nervus2",
)


class MemoryGraph:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=5)
        return self._pool

    async def store_life_event(
        self,
        event_type: str,
        title: str,
        description: str = "",
        metadata: dict = None,
        tags: list[str] = None,
        source_app: str = "",
        embedding: list[float] = None,
        timestamp: datetime = None,
    ) -> str:
        pool = await self._get_pool()
        event_id = str(uuid4())
        ts = timestamp or datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO life_events
                    (id, event_type, timestamp, title, description, metadata,
                     embedding, tags, source_app)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                event_id, event_type, ts, title, description,
                json.dumps(metadata or {}),
                embedding,
                tags or [],
                source_app,
            )
        return event_id

    async def store_knowledge(
        self,
        content_type: str,
        title: str,
        content: str = "",
        summary: str = "",
        source_url: str = "",
        tags: list[str] = None,
        embedding: list[float] = None,
    ) -> str:
        pool = await self._get_pool()
        item_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_items
                    (id, content_type, title, content, summary, source_url, tags, embedding)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                item_id, content_type, title, content, summary,
                source_url, tags or [], embedding,
            )
        return item_id

    async def semantic_search(
        self,
        embedding: list[float],
        table: str = "knowledge_items",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, title, summary, tags, created_at,
                       embedding <=> $1::vector AS distance
                FROM {table}
                WHERE embedding IS NOT NULL
                ORDER BY distance LIMIT $2
                """,
                vec_str, limit,
            )
        return [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "summary": r.get("summary", ""),
                "tags": list(r.get("tags", [])),
                "similarity": float(1 - r["distance"]),
            }
            for r in rows
        ]
