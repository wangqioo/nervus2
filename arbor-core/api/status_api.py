"""Status and health API for Arbor Core v2."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from infra.redis_client import get_redis
from infra.postgres_client import get_pool
from infra.nats_client import get_nc

router = APIRouter(tags=["status"])


@router.get("/health")
async def health():
    checks = {}
    try:
        nc = await get_nc()
        checks["nats"] = "ok" if nc.is_connected else "disconnected"
    except Exception as e:
        checks["nats"] = f"error: {e}"
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
    return {
        "healthy": all(v == "ok" for v in checks.values()),
        "checks": checks,
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
async def status(request: Request):
    registry = request.app.state.registry
    flow_loader = request.app.state.flow_loader
    apps = registry.list_all()
    return {
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "apps": {"registered": len(apps)},
        "flows": {"loaded": len(flow_loader.list_flows())},
        "architecture": "v2 (fast-router only, Personal Model handles intelligence)",
    }


@router.get("/flows")
async def list_flows(request: Request):
    flow_loader = request.app.state.flow_loader
    return {"flows": flow_loader.list_flows()}
