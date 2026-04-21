"""DimensionSnapshot — historical record persisted to PostgreSQL + pgvector.

Written by Model Updater on every dimension state change.
Enables time-series queries and semantic retrieval over past states.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from infra.postgres_client import get_pool

logger = logging.getLogger(__name__)


class DimensionSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    dim_id: str
    inferred_value: dict[str, Any]
    confidence: float
    source_event_ids: list[str] = Field(default_factory=list)
    semantic_embedding: Optional[list[float]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    correction_applied: bool = False


class InsightRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    dimensions_involved: list[str]
    correlation_type: str         # e.g. "sleep-stress", "nutrition-focus"
    description: str
    confidence: float
    recommendation: Optional[str] = None
    semantic_embedding: Optional[list[float]] = None
    expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


async def save_snapshot(snap: DimensionSnapshot) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        embedding_val = snap.semantic_embedding or None
        await conn.execute(
            """
            INSERT INTO dimension_snapshots
                (id, dim_id, inferred_value, confidence, source_event_ids,
                 semantic_embedding, timestamp, version, correction_applied)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            snap.id,
            snap.dim_id,
            json.dumps(snap.inferred_value),
            snap.confidence,
            snap.source_event_ids,
            embedding_val,
            snap.timestamp,
            snap.version,
            snap.correction_applied,
        )
    logger.debug("Snapshot saved: %s @ %s", snap.dim_id, snap.timestamp)


async def get_history(
    dim_id: str,
    limit: int = 50,
    since: Optional[datetime] = None,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if since:
            rows = await conn.fetch(
                """
                SELECT id, dim_id, inferred_value, confidence, timestamp, version
                FROM dimension_snapshots
                WHERE dim_id = $1 AND timestamp >= $2
                ORDER BY timestamp DESC LIMIT $3
                """,
                dim_id, since, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, dim_id, inferred_value, confidence, timestamp, version
                FROM dimension_snapshots
                WHERE dim_id = $1
                ORDER BY timestamp DESC LIMIT $2
                """,
                dim_id, limit,
            )
    return [
        {
            "id": str(r["id"]),
            "dim_id": r["dim_id"],
            "inferred_value": json.loads(r["inferred_value"]),
            "confidence": float(r["confidence"]),
            "timestamp": r["timestamp"].isoformat(),
            "version": r["version"],
        }
        for r in rows
    ]


async def semantic_search_snapshots(
    embedding: list[float],
    dim_id: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Find historically similar dimension states by vector similarity."""
    pool = await get_pool()
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    async with pool.acquire() as conn:
        if dim_id:
            rows = await conn.fetch(
                """
                SELECT id, dim_id, inferred_value, confidence, timestamp,
                       semantic_embedding <=> $1::vector AS distance
                FROM dimension_snapshots
                WHERE dim_id = $2 AND semantic_embedding IS NOT NULL
                ORDER BY distance LIMIT $3
                """,
                vec_str, dim_id, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, dim_id, inferred_value, confidence, timestamp,
                       semantic_embedding <=> $1::vector AS distance
                FROM dimension_snapshots
                WHERE semantic_embedding IS NOT NULL
                ORDER BY distance LIMIT $2
                """,
                vec_str, limit,
            )
    return [
        {
            "id": str(r["id"]),
            "dim_id": r["dim_id"],
            "inferred_value": json.loads(r["inferred_value"]),
            "confidence": float(r["confidence"]),
            "timestamp": r["timestamp"].isoformat(),
            "similarity": float(1 - r["distance"]),
        }
        for r in rows
    ]


async def save_insight(insight: InsightRecord) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO insight_records
                (id, dimensions_involved, correlation_type, description,
                 confidence, recommendation, semantic_embedding, expires_at, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            insight.id,
            insight.dimensions_involved,
            insight.correlation_type,
            insight.description,
            insight.confidence,
            insight.recommendation,
            insight.semantic_embedding,
            insight.expires_at,
            insight.created_at,
        )


async def get_recent_insights(limit: int = 20) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, dimensions_involved, correlation_type, description,
                   confidence, recommendation, created_at, expires_at
            FROM insight_records
            WHERE expires_at IS NULL OR expires_at > NOW()
            ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )
    return [
        {
            "id": str(r["id"]),
            "dimensions_involved": list(r["dimensions_involved"]),
            "correlation_type": r["correlation_type"],
            "description": r["description"],
            "confidence": float(r["confidence"]),
            "recommendation": r["recommendation"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def apply_correction(
    dim_id: str,
    corrected_value: dict,
    confidence: float = 1.0,
) -> None:
    """Insert a correction snapshot (user-provided ground truth)."""
    snap = DimensionSnapshot(
        dim_id=dim_id,
        inferred_value=corrected_value,
        confidence=confidence,
        correction_applied=True,
    )
    await save_snapshot(snap)
