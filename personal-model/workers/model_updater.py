"""Model Updater — 5-minute cycle that translates raw NATS events into dimension inferences.

Lifecycle:
1. Subscribes to all NATS domains via wildcard '>'
2. Buffers incoming events in Redis (list) with a 10-minute TTL
3. Every UPDATE_INTERVAL seconds:
   a. Drains the event buffer
   b. Groups events by which dimensions they affect
   c. For each affected dimension, calls the LLM with a focused prompt
   d. Writes updated DimensionState to Redis
   e. Persists a DimensionSnapshot to PostgreSQL

Cold-start handling:
- Phase 0 (days 0-3): accumulate only, do not infer
- Phase 1 (days 4-14): infer but mark low confidence
- Phase 2 (day 15+): full operation
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from infra.nats_client import connect as nats_connect
from infra.redis_client import get_redis, event_buffer_key, cold_start_key, last_updater_run_key
from infra.llm_client import get_llm
from model.dimensions import ALL_DIMENSIONS, get_dims_for_events, DimensionDefinition
from model.state import DimensionState, get_state, set_state, acquire_lock, release_lock
from model.snapshot import DimensionSnapshot, save_snapshot

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = int(os.getenv("MODEL_UPDATER_INTERVAL", str(5 * 60)))  # 5 minutes
EVENT_BUFFER_TTL = int(os.getenv("EVENT_BUFFER_TTL", str(10 * 60)))     # 10 minutes
MAX_EVENTS_PER_DIM = int(os.getenv("MAX_EVENTS_PER_DIM", "20"))

# Cold-start thresholds (seconds since first event)
PHASE1_THRESHOLD = 3 * 86_400   # 3 days
PHASE2_THRESHOLD = 14 * 86_400  # 14 days


class ModelUpdater:
    def __init__(self):
        self._running = False
        self._first_event_ts: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        nc, _ = await nats_connect()

        # Subscribe to every subject with a single wildcard
        await nc.subscribe(">", cb=self._on_event)
        logger.info("ModelUpdater: subscribed to all NATS subjects")

        asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # NATS event handler — fast path, just buffers to Redis
    # ------------------------------------------------------------------

    async def _on_event(self, msg) -> None:
        try:
            subject = msg.subject
            # Skip internal system subjects
            if subject.startswith("_NATS") or subject.startswith("pm."):
                return

            redis = await get_redis()
            record = json.dumps({
                "subject": subject,
                "data": msg.data.decode("utf-8", errors="replace")[:2000],
                "ts": time.time(),
            })
            # Push to list, trim to 500 events max, set TTL
            pipe = redis.pipeline()
            pipe.lpush(event_buffer_key(), record)
            pipe.ltrim(event_buffer_key(), 0, 499)
            pipe.expire(event_buffer_key(), EVENT_BUFFER_TTL)
            await pipe.execute()

            # Track first event for cold-start phase calculation
            if self._first_event_ts is None:
                self._first_event_ts = time.time()

        except Exception as exc:
            logger.error("ModelUpdater: error buffering event: %s", exc)

    # ------------------------------------------------------------------
    # Main loop — runs every UPDATE_INTERVAL seconds
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        while self._running:
            await asyncio.sleep(UPDATE_INTERVAL)
            try:
                await self._run_update_cycle()
            except Exception as exc:
                logger.exception("ModelUpdater: cycle error: %s", exc)

    async def _run_update_cycle(self) -> None:
        redis = await get_redis()
        phase = await self._get_cold_start_phase()

        if phase == 0:
            logger.info("ModelUpdater: Phase 0 — accumulating, skipping inference")
            return

        # Drain the event buffer atomically
        pipe = redis.pipeline()
        pipe.lrange(event_buffer_key(), 0, -1)
        pipe.delete(event_buffer_key())
        results = await pipe.execute()
        raw_events: list[str] = results[0] or []

        if not raw_events:
            logger.debug("ModelUpdater: no events in buffer, skipping cycle")
            return

        events = self._parse_events(raw_events)
        subjects = [e["subject"] for e in events]
        affected_dims = get_dims_for_events(subjects)

        logger.info(
            "ModelUpdater: %d events → %d affected dimensions (phase=%d)",
            len(events), len(affected_dims), phase,
        )

        for dim in affected_dims:
            await self._update_dimension(dim, events, phase)

        # Record last run time
        await redis.set(last_updater_run_key(), datetime.now(timezone.utc).isoformat())

    async def _update_dimension(
        self,
        dim: DimensionDefinition,
        all_events: list[dict],
        phase: int,
    ) -> None:
        # Filter to events relevant for this dimension
        relevant = [
            e for e in all_events
            if any(
                self._nats_match(pat, e["subject"])
                for pat in dim.relevant_events
            )
        ][:MAX_EVENTS_PER_DIM]

        if not relevant:
            return

        # Try to acquire update lock
        if not await acquire_lock(dim.id):
            logger.debug("ModelUpdater: dimension %s is locked, skipping", dim.id)
            return

        try:
            current = await get_state(dim.id)
            new_state = await self._infer_dimension(dim, relevant, current, phase)
            if new_state:
                written_state = await set_state(new_state)
                await self._persist_snapshot(written_state, relevant)
        finally:
            await release_lock(dim.id)

    async def _infer_dimension(
        self,
        dim: DimensionDefinition,
        events: list[dict],
        current: DimensionState | None,
        phase: int,
    ) -> DimensionState | None:
        llm = get_llm()

        # Build context section from current state
        current_ctx = ""
        if current and current.current_value:
            current_ctx = f"\nCurrent known state: {json.dumps(current.current_value)}"

        # Build event summary (keep prompt tight for Jetson)
        event_lines = []
        for e in events:
            ts = datetime.fromtimestamp(e["ts"], tz=timezone.utc).strftime("%H:%M")
            # Try to parse payload for cleaner display
            try:
                payload = json.loads(e["data"])
                summary = json.dumps(payload)[:300]
            except Exception:
                summary = e["data"][:300]
            event_lines.append(f"[{ts}] {e['subject']}: {summary}")

        events_text = "\n".join(event_lines)

        prompt = (
            f"Dimension: {dim.name} ({dim.id})\n"
            f"Description: {dim.description}\n"
            f"{current_ctx}\n\n"
            f"Recent events ({len(events)}):\n{events_text}\n\n"
            f"{dim.inference_prompt}\n\n"
            "Respond ONLY with valid JSON. No markdown, no explanation."
        )

        system = (
            "You are the inference engine for a personal AI model running on an edge device. "
            "Your job is to update a single dimension based on recent sensor/app events. "
            "Be concise. Return only the JSON object described in the prompt."
        )

        try:
            result = await llm.chat_json(prompt, system=system)
        except Exception as exc:
            logger.error("ModelUpdater: LLM error for %s: %s", dim.id, exc)
            return None

        if not result:
            return None

        # Phase 1: reduce confidence
        confidence = 0.85 if phase == 2 else 0.45

        return DimensionState(
            dim_id=dim.id,
            current_value=result,
            confidence=confidence,
            ttl_seconds=dim.ttl_seconds,
            source_events=[e["subject"] for e in events],
            version=(current.version if current else 0),
        )

    async def _persist_snapshot(
        self,
        state: DimensionState,
        events: list[dict],
    ) -> None:
        llm = get_llm()
        # Generate embedding for semantic search
        embed_text = f"{state.dim_id}: {json.dumps(state.current_value)}"
        try:
            embedding = await llm.embed(embed_text)
        except Exception:
            embedding = None

        snap = DimensionSnapshot(
            dim_id=state.dim_id,
            inferred_value=state.current_value,
            confidence=state.confidence,
            source_event_ids=[e.get("subject", "") for e in events],
            semantic_embedding=embedding,
            version=state.version,
        )
        try:
            await save_snapshot(snap)
        except Exception as exc:
            logger.error("ModelUpdater: snapshot save failed for %s: %s", state.dim_id, exc)

    # ------------------------------------------------------------------
    # Cold-start phase logic
    # ------------------------------------------------------------------

    async def _get_cold_start_phase(self) -> int:
        if self._first_event_ts is None:
            # Check Redis for stored first-event timestamp
            redis = await get_redis()
            stored = await redis.get("pm:first_event_ts")
            if stored:
                self._first_event_ts = float(stored)
            else:
                # No events yet — check if buffer has any
                count = await redis.llen(event_buffer_key())
                if count > 0:
                    self._first_event_ts = time.time()
                    await redis.set("pm:first_event_ts", str(self._first_event_ts))
                else:
                    return 0

        elapsed = time.time() - self._first_event_ts
        if elapsed < PHASE1_THRESHOLD:
            return 0
        if elapsed < PHASE2_THRESHOLD:
            return 1
        return 2

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_events(raw: list[str]) -> list[dict[str, Any]]:
        parsed = []
        for r in raw:
            try:
                parsed.append(json.loads(r))
            except Exception:
                pass
        return parsed

    @staticmethod
    def _nats_match(pattern: str, subject: str) -> bool:
        from model.dimensions import _nats_match
        return _nats_match(pattern, subject)
