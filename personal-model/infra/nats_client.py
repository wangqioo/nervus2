"""NATS JetStream client singleton for Personal Model service."""
import asyncio
import logging
import os
from typing import Callable, Optional

import nats
from nats.aio.client import Client
from nats.js import JetStreamContext

logger = logging.getLogger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")

_nc: Optional[Client] = None
_js: Optional[JetStreamContext] = None


async def connect() -> tuple[Client, JetStreamContext]:
    global _nc, _js
    if _nc and _nc.is_connected:
        return _nc, _js

    _nc = await nats.connect(
        NATS_URL,
        reconnect_time_wait=2,
        max_reconnect_attempts=-1,
        error_cb=_on_error,
        disconnected_cb=_on_disconnect,
        reconnected_cb=_on_reconnect,
    )
    _js = _nc.jetstream()
    logger.info("NATS connected: %s", NATS_URL)
    return _nc, _js


async def get_nc() -> Client:
    nc, _ = await connect()
    return nc


async def get_js() -> JetStreamContext:
    _, js = await connect()
    return js


async def subscribe(subject: str, handler: Callable, queue: str = "") -> None:
    nc = await get_nc()
    await nc.subscribe(subject, cb=handler, queue=queue)
    logger.debug("Subscribed to NATS subject: %s", subject)


async def publish(subject: str, payload: bytes) -> None:
    nc = await get_nc()
    await nc.publish(subject, payload)


async def close() -> None:
    global _nc, _js
    if _nc and _nc.is_connected:
        await _nc.drain()
    _nc = None
    _js = None


async def _on_error(e: Exception) -> None:
    logger.error("NATS error: %s", e)


async def _on_disconnect() -> None:
    logger.warning("NATS disconnected")


async def _on_reconnect() -> None:
    logger.info("NATS reconnected")
