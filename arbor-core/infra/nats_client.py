"""NATS client singleton for Arbor Core v2."""
import logging
import os
from typing import Optional

import nats
from nats.aio.client import Client
from nats.js import JetStreamContext

logger = logging.getLogger(__name__)
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

_nc: Optional[Client] = None
_js: Optional[JetStreamContext] = None


async def connect():
    global _nc, _js
    if _nc and _nc.is_connected:
        return _nc, _js
    _nc = await nats.connect(NATS_URL, reconnect_time_wait=2, max_reconnect_attempts=-1)
    _js = _nc.jetstream()
    logger.info("NATS connected: %s", NATS_URL)
    return _nc, _js


async def get_nc() -> Client:
    nc, _ = await connect()
    return nc


async def publish(subject: str, payload: bytes) -> None:
    nc = await get_nc()
    await nc.publish(subject, payload)


async def close() -> None:
    global _nc, _js
    if _nc and _nc.is_connected:
        await _nc.drain()
    _nc = None
    _js = None
