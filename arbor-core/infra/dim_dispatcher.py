"""DimUpdateDispatcher — fans out Personal Model dimension updates to subscribed apps.

When Personal Model publishes `pm.dimension.updated.<dim_id>`,
this dispatcher looks up which apps have that dim_id in their
model_subscriptions and calls their /intake/dim_update endpoint.

This is the V2 replacement for SemanticRouter.
"""
import json
import logging

logger = logging.getLogger(__name__)


class DimUpdateDispatcher:
    def __init__(self, registry):
        self._registry = registry

    async def handle(self, msg) -> None:
        subject = msg.subject
        # subject format: pm.dimension.updated.<dim_id>
        parts = subject.split(".")
        if len(parts) < 4:
            return

        dim_id = parts[3]

        try:
            data = json.loads(msg.data.decode("utf-8", errors="replace"))
        except Exception:
            return

        subscribed_apps = self._registry.apps_subscribed_to_dim(dim_id)
        if not subscribed_apps:
            return

        logger.debug(
            "Dimension update %s → dispatching to %d app(s)",
            dim_id, len(subscribed_apps),
        )

        dim_payload = {
            "dim_id": dim_id,
            "state": data.get("current_value", {}),
            "confidence": data.get("confidence", 0),
            "last_updated": data.get("last_updated"),
        }

        for app in subscribed_apps:
            await self._registry.call_intake(app, "dim_update", dim_payload)
