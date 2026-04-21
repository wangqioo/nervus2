"""GET /health — liveness check.
GET /status — full system snapshot.
GET /cold-start — cold-start phase and progress.
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter

from infra.redis_client import get_redis, last_updater_run_key, last_insight_run_key, cold_start_key
from infra.postgres_client import get_pool
from model.state import get_all_states
from model.dimensions import ALL_DIMENSIONS

router = APIRouter(tags=["status"])

SERVICE_VERSION = os.getenv("SERVICE_VERSION", "2.0.0")


@router.get("/health")
async def health():
    """Quick liveness check — tests Redis and PostgreSQL connectivity."""
    checks = {}

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"

    healthy = all(v == "ok" for v in checks.values())
    return {
        "healthy": healthy,
        "checks": checks,
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
async def status():
    """Full system snapshot: dimension coverage, worker run times, infrastructure."""
    all_states = await get_all_states()
    populated = sum(1 for v in all_states.values() if v is not None)
    avg_confidence = (
        sum(s.confidence for s in all_states.values() if s is not None) / max(populated, 1)
    )

    redis = await get_redis()
    last_update = await redis.get(last_updater_run_key())
    last_insight = await redis.get(last_insight_run_key())
    buffer_len = await redis.llen("pm:event_buffer")
    first_event_ts = await redis.get("pm:first_event_ts")

    # Compute cold-start phase
    phase = 0
    elapsed_days = None
    if first_event_ts:
        import time
        elapsed = time.time() - float(first_event_ts)
        elapsed_days = round(elapsed / 86_400, 1)
        if elapsed >= 14 * 86_400:
            phase = 2
        elif elapsed >= 3 * 86_400:
            phase = 1

    # Dimension breakdown by category
    by_category: dict[str, dict] = {}
    for dim in ALL_DIMENSIONS:
        cat = dim.category.value
        if cat not in by_category:
            by_category[cat] = {"total": 0, "populated": 0}
        by_category[cat]["total"] += 1
        if all_states.get(dim.id) is not None:
            by_category[cat]["populated"] += 1

    return {
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cold_start": {
            "phase": phase,
            "elapsed_days": elapsed_days,
            "description": ["Accumulating", "Low-confidence inference", "Full operation"][phase],
        },
        "dimensions": {
            "total": len(ALL_DIMENSIONS),
            "populated": populated,
            "coverage_pct": round(populated / len(ALL_DIMENSIONS) * 100, 1),
            "avg_confidence": round(avg_confidence, 2),
            "by_category": by_category,
        },
        "workers": {
            "model_updater": {
                "last_run": last_update,
                "event_buffer_size": buffer_len,
            },
            "insight_engine": {
                "last_run": last_insight,
            },
        },
    }


@router.get("/cold-start")
async def cold_start_status():
    """Detailed cold-start progress and what the user can do to accelerate it."""
    import time
    redis = await get_redis()
    first_event_ts = await redis.get("pm:first_event_ts")

    if not first_event_ts:
        return {
            "phase": 0,
            "phase_name": "Not started",
            "message": "No events received yet. Start using your apps to begin.",
            "progress_pct": 0,
            "days_elapsed": 0,
            "days_until_phase2": 14,
        }

    elapsed = time.time() - float(first_event_ts)
    elapsed_days = elapsed / 86_400
    days_to_phase2 = max(0, 14 - elapsed_days)

    if elapsed >= 14 * 86_400:
        phase, phase_name = 2, "Full operation"
        msg = "Personal model is fully operational. All dimensions actively inferred."
        progress = 100
    elif elapsed >= 3 * 86_400:
        phase, phase_name = 1, "Low-confidence inference"
        msg = "Initial inferences are active. Confidence will improve as more data accumulates."
        progress = int(40 + (elapsed_days - 3) / 11 * 60)
    else:
        phase, phase_name = 0, "Accumulating data"
        msg = "Collecting behavioral data. Inference begins on day 3."
        progress = int(elapsed_days / 3 * 40)

    return {
        "phase": phase,
        "phase_name": phase_name,
        "message": msg,
        "progress_pct": min(progress, 100),
        "days_elapsed": round(elapsed_days, 1),
        "days_until_phase2": round(days_to_phase2, 1),
        "tip": (
            "Use more apps (calorie tracker, meeting notes, knowledge base) "
            "to accelerate model learning — inference begins at day 3."
            if phase < 2 else None
        ),
    }
