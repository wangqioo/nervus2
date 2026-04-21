"""NervusApp — the primary SDK surface for building nervus2-compatible apps.

Provides decorator-based API for:
- Handling raw NATS events: @app.on("subject")
- Handling Personal Model dimension updates: @app.on_dimension("dim_id")
- Declaring actions: @app.action("name")
- Exposing state: @app.state

NSI v2 endpoints are auto-wired onto a FastAPI instance.
Dimension subscription updates arrive via POST /intake/dim_update.
"""
import asyncio
import json
import logging
import os
from typing import Any, Callable, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .models import Event, Manifest, DimSubscription, SubscribeConfig, ActionSpec
from .bus import SynapseBus
from .context import Context
from .memory import MemoryGraph
from .llm import LLMClient
from .model import PersonalModelClient

logger = logging.getLogger(__name__)


class NervusApp:
    def __init__(self, app_id: str, name: str = "", description: str = ""):
        self.app_id = app_id
        self.name = name or app_id
        self.description = description
        self.version = os.getenv("APP_VERSION", "1.0.0")
        self.port = int(os.getenv("APP_PORT", "8000"))

        self._event_handlers: dict[str, Callable] = {}
        self._dim_handlers: dict[str, Callable] = {}
        self._action_handlers: dict[str, Callable] = {}
        self._state_handler: Optional[Callable] = None
        self._subscribes: list[SubscribeConfig] = []
        self._publishes: list[str] = []
        self._dim_subscriptions: list[DimSubscription] = []
        self._actions: list[ActionSpec] = []

        # Shared infra clients (lazily initialized)
        self._bus: Optional[SynapseBus] = None
        self._context: Optional[Context] = None
        self._memory: Optional[MemoryGraph] = None
        self._llm: Optional[LLMClient] = None
        self._model: Optional[PersonalModelClient] = None

        self._fastapi: Optional[FastAPI] = None

    # ------------------------------------------------------------------
    # Decorators
    # ------------------------------------------------------------------

    def on(self, subject: str, filter: dict = None, handler_path: str = None):
        """Subscribe to a raw NATS event subject."""
        def decorator(fn: Callable):
            self._event_handlers[subject] = fn
            hp = handler_path or f"/intake/{subject.replace('.', '_')}"
            self._subscribes.append(SubscribeConfig(
                subject=subject,
                handler_path=hp,
                filter=filter or {},
            ))
            return fn
        return decorator

    def on_dimension(
        self,
        dim_id: str,
        min_confidence: float = 0.5,
    ):
        """Subscribe to Personal Model dimension updates (v2)."""
        def decorator(fn: Callable):
            self._dim_handlers[dim_id] = fn
            self._dim_subscriptions.append(DimSubscription(
                dim_id=dim_id,
                handler_path="/intake/dim_update",
                min_confidence=min_confidence,
            ))
            return fn
        return decorator

    def action(self, name: str, description: str = "", input_schema: dict = None, output_schema: dict = None):
        """Declare an app action callable by Arbor Core."""
        def decorator(fn: Callable):
            self._action_handlers[name] = fn
            self._actions.append(ActionSpec(
                name=name,
                description=description or fn.__doc__ or "",
                input_schema=input_schema or {},
                output_schema=output_schema or {},
            ))
            return fn
        return decorator

    def state(self, fn: Callable):
        """Register a function that returns the app's current state snapshot."""
        self._state_handler = fn
        return fn

    def publishes(self, *subjects: str):
        """Declare NATS subjects this app will emit."""
        self._publishes.extend(subjects)
        return self

    # ------------------------------------------------------------------
    # Infrastructure accessors
    # ------------------------------------------------------------------

    @property
    def bus(self) -> SynapseBus:
        if self._bus is None:
            self._bus = SynapseBus()
        return self._bus

    @property
    def context(self) -> Context:
        if self._context is None:
            self._context = Context()
        return self._context

    @property
    def memory(self) -> MemoryGraph:
        if self._memory is None:
            self._memory = MemoryGraph()
        return self._memory

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    @property
    def model(self) -> PersonalModelClient:
        if self._model is None:
            self._model = PersonalModelClient()
        return self._model

    # ------------------------------------------------------------------
    # FastAPI wiring
    # ------------------------------------------------------------------

    def build_fastapi(self) -> FastAPI:
        if self._fastapi:
            return self._fastapi

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await self.bus.connect()
            await self._register_with_arbor()
            yield
            await self.bus.close()

        api = FastAPI(title=self.name, version=self.version, lifespan=lifespan)

        @api.get("/manifest")
        async def manifest():
            return self._build_manifest().model_dump()

        @api.post("/intake/{handler_name}")
        async def intake(handler_name: str, request: Request):
            body = await request.json()
            # Dimension update path
            if handler_name == "dim_update":
                return await self._dispatch_dim_update(body)
            # Raw event path
            event = Event(**body) if isinstance(body, dict) and "subject" in body else Event(
                subject=handler_name.replace("_", "."), payload=body
            )
            return await self._dispatch_event(handler_name, event)

        @api.get("/query/{query_type}")
        async def query(query_type: str, request: Request):
            # Apps can override this with their own handlers — default returns empty
            return {"type": query_type, "results": []}

        @api.post("/action/{action_name}")
        async def action(action_name: str, request: Request):
            body = await request.json()
            handler = self._action_handlers.get(action_name)
            if not handler:
                raise HTTPException(404, f"Action '{action_name}' not found")
            result = await handler(body) if asyncio.iscoroutinefunction(handler) else handler(body)
            return {"action": action_name, "result": result}

        @api.get("/state")
        async def state():
            if self._state_handler:
                s = await self._state_handler() if asyncio.iscoroutinefunction(self._state_handler) else self._state_handler()
                return s
            return {"app_id": self.app_id, "status": "running"}

        @api.get("/health")
        async def health():
            return {"healthy": True, "app_id": self.app_id}

        self._fastapi = api
        return api

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_manifest(self) -> Manifest:
        return Manifest(
            id=self.app_id,
            name=self.name,
            version=self.version,
            description=self.description,
            subscribes=self._subscribes,
            publishes=self._publishes,
            actions=self._actions,
            model_subscriptions=self._dim_subscriptions,
        )

    async def _register_with_arbor(self) -> None:
        arbor_url = os.getenv("ARBOR_URL", "http://arbor-core:8090")
        app_host = os.getenv("APP_HOST", self.app_id)
        endpoint = f"http://{app_host}:{self.port}"
        payload = {
            "app_id": self.app_id,
            "manifest": self._build_manifest().model_dump(),
            "endpoint": endpoint,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{arbor_url}/register", json=payload)
                r.raise_for_status()
                logger.info("Registered with Arbor Core: %s", self.app_id)
        except Exception as exc:
            logger.warning("Could not register with Arbor Core: %s", exc)

    async def _dispatch_event(self, handler_name: str, event: Event) -> dict:
        # Match by subject pattern
        for subject, handler in self._event_handlers.items():
            from nervus_sdk.models import _nats_match_sdk
            if _nats_match_sdk(subject, event.subject):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(event)
                    else:
                        result = handler(event)
                    return {"handled": True, "result": result}
                except Exception as exc:
                    logger.error("Handler error [%s]: %s", subject, exc)
                    return {"handled": False, "error": str(exc)}
        return {"handled": False, "reason": "no matching handler"}

    async def _dispatch_dim_update(self, body: dict) -> dict:
        dim_id = body.get("dim_id")
        confidence = float(body.get("confidence", 0))
        state = body.get("state", {})

        handler = self._dim_handlers.get(dim_id)
        if not handler:
            return {"handled": False, "reason": f"no handler for dimension {dim_id}"}

        # Check min_confidence threshold
        sub = next((s for s in self._dim_subscriptions if s.dim_id == dim_id), None)
        if sub and confidence < sub.min_confidence:
            return {"handled": False, "reason": "confidence below threshold"}

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(state, confidence)
            else:
                result = handler(state, confidence)
            return {"handled": True, "dim_id": dim_id, "result": result}
        except Exception as exc:
            logger.error("Dimension handler error [%s]: %s", dim_id, exc)
            return {"handled": False, "error": str(exc)}
