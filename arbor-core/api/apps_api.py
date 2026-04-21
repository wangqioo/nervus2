"""POST /register — register an app with Arbor Core."""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from infra.postgres_client import get_pool
from infra.nats_client import publish

logger = logging.getLogger(__name__)
router = APIRouter(tags=["apps"])


class RegisterRequest(BaseModel):
    app_id: str
    manifest: dict
    endpoint: str


@router.post("/register")
async def register_app(req: RegisterRequest, request: Request):
    registry = request.app.state.registry
    app = registry.register(req.app_id, req.manifest, req.endpoint)

    # Persist to PostgreSQL
    pool = await get_pool()
    dim_subs = [s["dim_id"] for s in req.manifest.get("model_subscriptions", [])]
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app_registry (app_id, manifest, model_subscriptions, endpoint, status, registered_at)
            VALUES ($1,$2,$3,$4,'active',NOW())
            ON CONFLICT (app_id) DO UPDATE
                SET manifest=$2, model_subscriptions=$3, endpoint=$4,
                    status='active', last_seen_at=NOW()
            """,
            req.app_id, json.dumps(req.manifest), dim_subs, req.endpoint,
        )

    await publish("system.app.registered", json.dumps({
        "app_id": req.app_id,
        "endpoint": req.endpoint,
        "ts": datetime.now(timezone.utc).isoformat(),
    }).encode())

    return {"registered": True, "app_id": req.app_id, "endpoint": req.endpoint}


@router.get("/list")
async def list_apps(request: Request):
    registry = request.app.state.registry
    return {
        "apps": [
            {
                "app_id": a.app_id,
                "name": a.manifest.get("name", a.app_id),
                "endpoint": a.endpoint,
                "dim_subscriptions": a.dim_subscriptions,
                "registered_at": a.registered_at.isoformat(),
            }
            for a in registry.list_all()
        ]
    }


@router.get("/{app_id}")
async def get_app(app_id: str, request: Request):
    registry = request.app.state.registry
    app = registry.get(app_id)
    if not app:
        raise HTTPException(404, f"App '{app_id}' not found")
    return {
        "app_id": app.app_id,
        "manifest": app.manifest,
        "endpoint": app.endpoint,
        "dim_subscriptions": app.dim_subscriptions,
        "registered_at": app.registered_at.isoformat(),
    }
