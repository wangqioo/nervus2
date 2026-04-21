"""Insight Engine — hourly cross-dimensional correlation analysis.

Runs every INSIGHT_INTERVAL seconds.
Reads all current dimension states, asks the LLM to find non-obvious
correlations and patterns that individual dimensions cannot detect alone.
Persists insights to PostgreSQL with confidence scores and expiry.

Examples of insights this engine can surface:
  - "High stress on days after <6h sleep — consider earlier bedtime"
  - "Reading velocity drops when cognitive load is high — protect morning blocks"
  - "Social rhythm is low this week; life satisfaction trending down"
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from infra.redis_client import get_redis, last_insight_run_key
from infra.llm_client import get_llm
from model.state import get_all_states, DimensionState
from model.snapshot import InsightRecord, save_insight, get_recent_insights

logger = logging.getLogger(__name__)

INSIGHT_INTERVAL = int(os.getenv("INSIGHT_INTERVAL", str(60 * 60)))   # 1 hour
MIN_DIMS_FOR_INSIGHT = int(os.getenv("MIN_DIMS_FOR_INSIGHT", "5"))    # need ≥5 dims populated
INSIGHT_EXPIRY_HOURS = int(os.getenv("INSIGHT_EXPIRY_HOURS", "72"))   # insights expire in 3 days
MAX_INSIGHTS_PER_CYCLE = int(os.getenv("MAX_INSIGHTS_PER_CYCLE", "5"))


SYSTEM_PROMPT = """\
You are the insight engine of a personal AI model running on an edge device.
Your job is to identify non-obvious correlations and actionable patterns across
the user's personal dimensions. Focus on useful, specific observations.
Do NOT surface observations that are already obvious from a single dimension.
Be honest about uncertainty — use confidence scores appropriately.
Respond only with valid JSON as specified."""


class InsightEngine:
    def __init__(self):
        self._running = False

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._run_loop())
        logger.info("InsightEngine: started (interval=%ds)", INSIGHT_INTERVAL)

    async def stop(self) -> None:
        self._running = False

    async def _run_loop(self) -> None:
        # Initial delay — let Model Updater run first
        await asyncio.sleep(60)
        while self._running:
            try:
                await self._run_insight_cycle()
            except Exception as exc:
                logger.exception("InsightEngine: cycle error: %s", exc)
            await asyncio.sleep(INSIGHT_INTERVAL)

    async def _run_insight_cycle(self) -> None:
        # Load all current dimension states
        all_states = await get_all_states()
        populated = {k: v for k, v in all_states.items() if v is not None}

        if len(populated) < MIN_DIMS_FOR_INSIGHT:
            logger.info(
                "InsightEngine: only %d dimensions populated (need %d), skipping",
                len(populated), MIN_DIMS_FOR_INSIGHT,
            )
            return

        # Build a compact dimensions summary for the prompt
        dim_summary = self._build_dim_summary(populated)

        # Load recent insights to avoid duplicates
        recent = await get_recent_insights(limit=10)
        recent_types = [r["correlation_type"] for r in recent]

        prompt = self._build_prompt(dim_summary, recent_types)

        llm = get_llm()
        try:
            result = await llm.chat_json(
                prompt,
                system=SYSTEM_PROMPT,
                max_tokens=1024,
            )
        except Exception as exc:
            logger.error("InsightEngine: LLM error: %s", exc)
            return

        insights_data = result.get("insights", [])
        if not isinstance(insights_data, list):
            logger.warning("InsightEngine: unexpected LLM response format")
            return

        saved = 0
        for item in insights_data[:MAX_INSIGHTS_PER_CYCLE]:
            insight = self._parse_insight(item)
            if insight:
                try:
                    await self._embed_insight(insight)
                    await save_insight(insight)
                    saved += 1
                except Exception as exc:
                    logger.error("InsightEngine: failed to save insight: %s", exc)

        redis = await get_redis()
        await redis.set(last_insight_run_key(), datetime.now(timezone.utc).isoformat())
        logger.info("InsightEngine: cycle complete — %d insights saved", saved)

    def _build_dim_summary(self, states: dict[str, DimensionState]) -> str:
        lines = []
        for dim_id, state in sorted(states.items()):
            # Pull summary field if present, else dump the full value (truncated)
            val = state.current_value
            summary = val.get("summary") if isinstance(val, dict) else None
            if not summary:
                summary = json.dumps(val)[:200]
            conf = f"{state.confidence:.0%}"
            age_min = int(
                (datetime.now(timezone.utc) - state.last_updated).total_seconds() / 60
            )
            lines.append(f"  {dim_id} ({conf}, {age_min}min ago): {summary}")
        return "\n".join(lines)

    def _build_prompt(self, dim_summary: str, recent_types: list[str]) -> str:
        avoid = ", ".join(recent_types) if recent_types else "none"
        return (
            f"Current Personal Model state:\n{dim_summary}\n\n"
            f"Recently surfaced correlation types (avoid repeating): {avoid}\n\n"
            "Identify up to 5 new cross-dimensional insights. For each insight return:\n"
            "- dimensions_involved: list of dimension IDs\n"
            "- correlation_type: short snake_case label (e.g. 'sleep_stress_link')\n"
            "- description: 1-2 sentence human-readable observation\n"
            "- confidence: 0.0-1.0\n"
            "- recommendation: actionable suggestion for the user (1 sentence, or null)\n\n"
            'Return JSON: {"insights": [...]}\n'
            "Only include insights with confidence ≥ 0.5. "
            "Do NOT include trivial observations like 'sleep affects energy'."
        )

    def _parse_insight(self, item: dict) -> InsightRecord | None:
        try:
            confidence = float(item.get("confidence", 0))
            if confidence < 0.5:
                return None
            expires_at = datetime.now(timezone.utc) + timedelta(hours=INSIGHT_EXPIRY_HOURS)
            return InsightRecord(
                dimensions_involved=list(item.get("dimensions_involved", [])),
                correlation_type=str(item.get("correlation_type", "unknown")),
                description=str(item.get("description", "")),
                confidence=confidence,
                recommendation=item.get("recommendation"),
                expires_at=expires_at,
            )
        except Exception as exc:
            logger.warning("InsightEngine: failed to parse insight item: %s", exc)
            return None

    async def _embed_insight(self, insight: InsightRecord) -> None:
        llm = get_llm()
        text = f"{insight.correlation_type}: {insight.description}"
        try:
            insight.semantic_embedding = await llm.embed(text)
        except Exception:
            pass  # embedding is optional — don't fail the save
