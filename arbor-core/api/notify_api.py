"""Notification API — global popup and notification history."""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

from infra.postgres_client import get_pool

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationRequest(BaseModel):
    title: str
    body: str = ""
    source_app: str = "system"
    metadata: dict = {}
    actions: list = []


@router.post("")
async def create_notification(req: NotificationRequest):
    pool = await get_pool()
    notif_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notifications (id, title, body, source_app, metadata, actions)
            VALUES ($1,$2,$3,$4,$5,$6)
            """,
            notif_id, req.title, req.body, req.source_app,
            json.dumps(req.metadata), json.dumps(req.actions),
        )
    return {"id": notif_id, "created": True}


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if unread_only:
            rows = await conn.fetch(
                "SELECT id,title,body,source_app,read,created_at FROM notifications WHERE read=FALSE ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT id,title,body,source_app,read,created_at FROM notifications ORDER BY created_at DESC LIMIT $1",
                limit,
            )
    return {
        "notifications": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "body": r["body"],
                "source_app": r["source_app"],
                "read": r["read"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE notifications SET read=TRUE WHERE id=$1", notif_id)
    return {"id": notif_id, "read": True}
