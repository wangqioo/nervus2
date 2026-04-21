"""FlowExecutor — executes JSON-defined multi-step flows."""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from infra.postgres_client import get_pool
from infra.nats_client import publish

logger = logging.getLogger(__name__)


class FlowExecutor:
    def __init__(self, registry):
        self._registry = registry

    async def execute(self, flow: dict, trigger_event: dict) -> None:
        flow_id = flow.get("id", "unknown")
        started = time.monotonic()
        status = "success"
        error = None

        try:
            context: dict[str, Any] = {"trigger": trigger_event}
            for step in flow.get("steps", []):
                result = await self._execute_step(step, context)
                step_id = step.get("id", "step")
                context[step_id] = {"result": result}
        except Exception as exc:
            status = "error"
            error = str(exc)
            logger.error("Flow %s failed: %s", flow_id, exc)
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            await self._log_execution(flow_id, trigger_event, status, duration_ms, error)

    async def _execute_step(self, step: dict, ctx: dict) -> Any:
        step_type = step.get("type")
        params = self._resolve_params(step.get("params", {}), ctx)

        if step_type == "app_action":
            app_id = params.get("app_id", "")
            action = params.get("action", "")
            return await self._registry.call_action(app_id, action, params.get("payload", {}))

        if step_type == "intake":
            app_id = params.get("app_id", "")
            handler = params.get("handler", "event")
            app = self._registry.get(app_id)
            if app:
                return await self._registry.call_intake(app, handler, params.get("payload", {}))
            return None

        if step_type == "emit_event":
            subject = params.get("subject", "")
            payload = params.get("payload", {})
            await publish(subject, json.dumps(payload).encode())
            return {"subject": subject}

        if step_type == "parallel":
            sub_steps = step.get("steps", [])
            results = await asyncio.gather(
                *[self._execute_step(s, ctx) for s in sub_steps],
                return_exceptions=True,
            )
            return results

        if step_type == "notification":
            return await self._send_notification(params, ctx)

        logger.warning("Unknown step type: %s", step_type)
        return None

    async def _send_notification(self, params: dict, ctx: dict) -> dict:
        title = params.get("title", "Nervus")
        body = params.get("body", "")
        pool = await get_pool()
        import uuid
        notif_id = str(uuid.uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO notifications (id, title, body, source_app) VALUES ($1,$2,$3,$4)",
                notif_id, title, body, params.get("source_app", "arbor-core"),
            )
        return {"notification_id": notif_id}

    @staticmethod
    def _resolve_params(params: dict, ctx: dict) -> dict:
        """Resolve JSONPath references like $.trigger.payload.file_path."""
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str) and v.startswith("$."):
                resolved[k] = FlowExecutor._jsonpath(v, ctx)
            elif isinstance(v, dict):
                resolved[k] = FlowExecutor._resolve_params(v, ctx)
            else:
                resolved[k] = v
        return resolved

    @staticmethod
    def _jsonpath(path: str, ctx: dict) -> Any:
        parts = path.lstrip("$").lstrip(".").split(".")
        current = ctx
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current

    async def _log_execution(
        self, flow_id: str, trigger: dict, status: str, duration_ms: int, error: Optional[str]
    ) -> None:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO flow_executions (flow_id, trigger_event, status, duration_ms, error)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    flow_id, json.dumps(trigger), status, duration_ms, error,
                )
        except Exception as exc:
            logger.warning("Failed to log flow execution: %s", exc)
