"""Shared Pydantic models for nervus2 SDK."""


def _nats_match_sdk(pattern: str, subject: str) -> bool:
    """NATS wildcard matching used by the SDK event dispatcher."""
    def _match(pat: list[str], sub: list[str]) -> bool:
        if not pat:
            return not sub
        if pat[0] == ">":
            return True
        if not sub:
            return False
        if pat[0] == "*" or pat[0] == sub[0]:
            return _match(pat[1:], sub[1:])
        return False
    return _match(pattern.split("."), subject.split("."))


from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    subject: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None


class DimSubscription(BaseModel):
    """Declares which Personal Model dimension this app subscribes to."""
    dim_id: str
    handler_path: str = "/intake/dim_update"   # endpoint that receives updates
    min_confidence: float = Field(0.5, ge=0.0, le=1.0)


class ActionSpec(BaseModel):
    name: str
    description: str
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)


class SubscribeConfig(BaseModel):
    subject: str
    handler_path: str
    filter: dict[str, Any] = Field(default_factory=dict)


class Manifest(BaseModel):
    model_config = {"protected_namespaces": ()}

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    # V1 fields
    subscribes: list[SubscribeConfig] = Field(default_factory=list)
    publishes: list[str] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(default_factory=list)
    context_reads: list[str] = Field(default_factory=list)
    context_writes: list[str] = Field(default_factory=list)
    memory_writes: list[str] = Field(default_factory=list)
    # V2 — dimension subscriptions (NEW)
    model_subscriptions: list[DimSubscription] = Field(default_factory=list)
