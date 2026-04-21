"""GET /dimensions — list all dimensions with current state.
GET /dimensions/{dim_id} — single dimension detail.
GET /dimensions/{dim_id}/history — time-series snapshots.
GET /insights — recent cross-dimensional insights.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from model.dimensions import ALL_DIMENSIONS, DIM_REGISTRY
from model.state import get_state, get_all_states
from model.snapshot import get_history, get_recent_insights

router = APIRouter(prefix="/dimensions", tags=["dimensions"])


@router.get("")
async def list_dimensions(category: Optional[str] = None):
    """List all 20 dimensions with their current state (if populated)."""
    all_states = await get_all_states()
    result = []
    for dim in ALL_DIMENSIONS:
        if category and dim.category.value != category:
            continue
        state = all_states.get(dim.id)
        result.append({
            "id": dim.id,
            "name": dim.name,
            "category": dim.category.value,
            "description": dim.description,
            "ttl_seconds": dim.ttl_seconds,
            "state": _format_state(state),
        })
    return {"dimensions": result, "total": len(result)}


@router.get("/{dim_id}")
async def get_dimension(dim_id: str):
    """Get a single dimension with its full current state."""
    dim = DIM_REGISTRY.get(dim_id)
    if not dim:
        raise HTTPException(status_code=404, detail=f"Dimension '{dim_id}' not found")

    state = await get_state(dim_id)
    return {
        "id": dim.id,
        "name": dim.name,
        "category": dim.category.value,
        "description": dim.description,
        "relevant_events": dim.relevant_events,
        "ttl_seconds": dim.ttl_seconds,
        "state": _format_state(state),
    }


@router.get("/{dim_id}/history")
async def get_dimension_history(
    dim_id: str,
    limit: int = Query(50, ge=1, le=200),
    since: Optional[datetime] = None,
):
    """Return time-series snapshots for a dimension."""
    if dim_id not in DIM_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Dimension '{dim_id}' not found")

    history = await get_history(dim_id, limit=limit, since=since)
    return {
        "dim_id": dim_id,
        "count": len(history),
        "history": history,
    }


# Insights live here logically (cross-dimensional output)
insights_router = APIRouter(prefix="/insights", tags=["insights"])


@insights_router.get("")
async def list_insights(limit: int = Query(20, ge=1, le=100)):
    """Return recent cross-dimensional insights from the Insight Engine."""
    insights = await get_recent_insights(limit=limit)
    return {"insights": insights, "count": len(insights)}


def _format_state(state) -> dict:
    if state is None:
        return {"populated": False}
    return {
        "populated": True,
        "current_value": state.current_value,
        "confidence": state.confidence,
        "last_updated": state.last_updated.isoformat(),
        "version": state.version,
        "stale": _is_stale(state),
    }


def _is_stale(state) -> bool:
    age = (datetime.now(timezone.utc) - state.last_updated).total_seconds()
    return age > state.ttl_seconds
