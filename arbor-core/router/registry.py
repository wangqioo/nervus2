"""AppRegistry — service discovery and action dispatch for Arbor Core v2."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

APP_CALL_TIMEOUT = float(10)


class RegisteredApp:
    def __init__(self, app_id: str, manifest: dict, endpoint: str):
        self.app_id = app_id
        self.manifest = manifest
        self.endpoint = endpoint.rstrip("/")
        self.registered_at = datetime.now(timezone.utc)
        self.last_seen_at = self.registered_at
        # Parse model_subscriptions for quick lookup
        self.model_subscriptions: list[dict] = manifest.get("model_subscriptions", [])

    @property
    def dim_subscriptions(self) -> list[str]:
        return [s["dim_id"] for s in self.model_subscriptions]


class AppRegistry:
    def __init__(self):
        self._apps: dict[str, RegisteredApp] = {}

    def register(self, app_id: str, manifest: dict, endpoint: str) -> RegisteredApp:
        app = RegisteredApp(app_id, manifest, endpoint)
        self._apps[app_id] = app
        logger.info("Registered app: %s @ %s", app_id, endpoint)
        return app

    def get(self, app_id: str) -> Optional[RegisteredApp]:
        return self._apps.get(app_id)

    def list_all(self) -> list[RegisteredApp]:
        return list(self._apps.values())

    def apps_subscribed_to_dim(self, dim_id: str) -> list[RegisteredApp]:
        return [a for a in self._apps.values() if dim_id in a.dim_subscriptions]

    def apps_for_subject(self, subject: str) -> list[RegisteredApp]:
        """Return apps that subscribe to the given NATS subject."""
        result = []
        for app in self._apps.values():
            for sub in app.manifest.get("subscribes", []):
                if _nats_match(sub["subject"], subject):
                    result.append(app)
                    break
        return result

    async def call_intake(
        self,
        app: RegisteredApp,
        handler_name: str,
        payload: dict,
    ) -> Optional[dict]:
        url = f"{app.endpoint}/intake/{handler_name}"
        try:
            async with httpx.AsyncClient(timeout=APP_CALL_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                app.last_seen_at = datetime.now(timezone.utc)
                return resp.json()
        except Exception as exc:
            logger.warning("intake call failed [%s → %s]: %s", app.app_id, handler_name, exc)
            return None

    async def call_action(
        self,
        app_id: str,
        action_name: str,
        params: dict,
    ) -> Optional[dict]:
        app = self._apps.get(app_id)
        if not app:
            logger.warning("Action call: app %s not found", app_id)
            return None
        url = f"{app.endpoint}/action/{action_name}"
        try:
            async with httpx.AsyncClient(timeout=APP_CALL_TIMEOUT) as client:
                resp = await client.post(url, json=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("action call failed [%s.%s]: %s", app_id, action_name, exc)
            return None

    async def get_state(self, app_id: str) -> Optional[dict]:
        app = self._apps.get(app_id)
        if not app:
            return None
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{app.endpoint}/state")
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return None


def _nats_match(pattern: str, subject: str) -> bool:
    def match(pat: list, sub: list) -> bool:
        if not pat:
            return not sub
        if pat[0] == ">":
            return True
        if not sub:
            return False
        if pat[0] in ("*", sub[0]):
            return match(pat[1:], sub[1:])
        return False
    return match(pattern.split("."), subject.split("."))
