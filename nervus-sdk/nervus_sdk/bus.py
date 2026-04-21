"""SynapseBus — NATS publish/subscribe wrapper for nervus2 apps."""
import json
import logging
import os
from typing import Any, Callable, Optional

import nats
from nats.aio.client import Client

logger = logging.getLogger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")


class SynapseBus:
    def __init__(self):
        self._nc: Optional[Client] = None

    async def connect(self) -> None:
        self._nc = await nats.connect(
            NATS_URL,
            reconnect_time_wait=2,
            max_reconnect_attempts=-1,
        )
        logger.info("SynapseBus connected: %s", NATS_URL)

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        if not self._nc:
            raise RuntimeError("SynapseBus not connected")
        await self._nc.publish(subject, json.dumps(payload).encode())

    async def subscribe(self, subject: str, handler: Callable, queue: str = "") -> None:
        if not self._nc:
            raise RuntimeError("SynapseBus not connected")
        await self._nc.subscribe(subject, cb=handler, queue=queue)

    async def close(self) -> None:
        if self._nc and self._nc.is_connected:
            await self._nc.drain()
        self._nc = None
