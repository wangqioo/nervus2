"""POST /corrections — user feedback to refine model inferences.

Corrections are the ground truth signal that the Model Updater uses
to calibrate its LLM prompts over time. Each correction:
1. Immediately updates the Redis current state with the corrected value
2. Persists a snapshot flagged as correction_applied=True
3. Publishes pm.dimension.corrected to NATS so apps can react
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from infra.nats_client import publish
from model.dimensions import DIM_REGISTRY
from model.state import DimensionState, get_state, set_state
from model.snapshot import apply_correction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/corrections", tags=["corrections"])


class CorrectionRequest(BaseModel):
    dim_id: str
    corrected_value: dict[str, Any] = Field(..., description="Ground-truth value to apply")
    note: str = Field("", max_length=500, description="Optional user note explaining correction")


class CorrectionResponse(BaseModel):
    accepted: bool
    dim_id: str
    new_state_version: int
    message: str


@router.post("", response_model=CorrectionResponse)
async def submit_correction(req: CorrectionRequest):
    if req.dim_id not in DIM_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Dimension '{req.dim_id}' not found")

    if not req.corrected_value:
        raise HTTPException(status_code=400, detail="corrected_value cannot be empty")

    dim = DIM_REGISTRY[req.dim_id]
    current = await get_state(req.dim_id)

    # Build corrected state — user corrections have confidence=1.0
    new_state = DimensionState(
        dim_id=req.dim_id,
        current_value=req.corrected_value,
        confidence=1.0,
        ttl_seconds=dim.ttl_seconds,
        source_events=["user:correction"],
        version=current.version if current else 0,
        last_updated=datetime.now(timezone.utc),
    )
    written_state = await set_state(new_state)

    # Persist as a ground-truth snapshot
    await apply_correction(req.dim_id, req.corrected_value, confidence=1.0)

    # Notify via NATS (correction-specific event, separate from normal update)
    event_payload = json.dumps({
        "dim_id": req.dim_id,
        "corrected_value": req.corrected_value,
        "note": req.note,
        "ts": datetime.now(timezone.utc).isoformat(),
    }).encode()
    try:
        await publish(f"pm.dimension.corrected.{req.dim_id}", event_payload)
    except Exception as exc:
        logger.warning("Could not publish correction event: %s", exc)

    logger.info("Correction applied: %s (v%d)", req.dim_id, written_state.version)

    return CorrectionResponse(
        accepted=True,
        dim_id=req.dim_id,
        new_state_version=written_state.version,
        message=f"Correction applied to '{dim.name}'. Model will incorporate this in the next update cycle.",
    )


@router.get("")
async def list_correction_history(dim_id: str | None = None, limit: int = 20):
    """List recent user corrections from the snapshot history."""
    from infra.postgres_client import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        if dim_id:
            rows = await conn.fetch(
                """
                SELECT id, dim_id, inferred_value, confidence, timestamp
                FROM dimension_snapshots
                WHERE correction_applied = TRUE AND dim_id = $1
                ORDER BY timestamp DESC LIMIT $2
                """,
                dim_id, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, dim_id, inferred_value, confidence, timestamp
                FROM dimension_snapshots
                WHERE correction_applied = TRUE
                ORDER BY timestamp DESC LIMIT $1
                """,
                limit,
            )
    return {
        "corrections": [
            {
                "id": str(r["id"]),
                "dim_id": r["dim_id"],
                "corrected_value": json.loads(r["inferred_value"]),
                "confidence": float(r["confidence"]),
                "timestamp": r["timestamp"].isoformat(),
            }
            for r in rows
        ]
    }
