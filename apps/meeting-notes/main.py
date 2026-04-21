"""Meeting Notes — nervus2 v2 app.

V2 changes vs V1:
- Subscribes to `stress_indicator` to add contextual note to meeting record
- Subscribes to `upcoming_context` to pre-fetch relevant knowledge before meetings
- Publishes meeting events for dimension inference (cognitive_load, social_rhythm)
"""
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, Event

logger = logging.getLogger(__name__)
APP_ID = "meeting-notes"

WHISPER_URL = os.getenv("WHISPER_URL", "http://whisper:9000")

app = NervusApp(
    app_id=APP_ID,
    name="Meeting Notes",
    description="Audio transcription + indexing with stress context awareness",
)
app.publishes(
    "meeting.recording.processed",
    "meeting.transcript.ready",
)

# -------------------------------------------------------------------------
# Dimension subscriptions
# -------------------------------------------------------------------------

_stress_level = "calm"
_upcoming_meetings: list[dict] = []


@app.on_dimension("stress_indicator", min_confidence=0.5)
async def on_stress(state: dict, confidence: float):
    global _stress_level
    _stress_level = state.get("level", "calm")
    logger.debug("Stress level updated: %s", _stress_level)


@app.on_dimension("upcoming_context", min_confidence=0.5)
async def on_upcoming(state: dict, confidence: float):
    """Pre-fetch relevant knowledge before a meeting if one is coming up soon."""
    global _upcoming_meetings
    if state.get("meeting_heavy") and state.get("next_event_in_minutes", 999) < 30:
        next_event = state.get("next_event_name", "")
        if next_event:
            logger.info("Meeting in <30min: %s — warming up knowledge base", next_event)
            # Publish a pre-fetch hint so knowledge-base can prioritize
            await app.bus.publish("meeting.preparation.needed", {
                "meeting_name": next_event,
                "minutes_until": state.get("next_event_in_minutes"),
                "ts": datetime.now(timezone.utc).isoformat(),
            })


# -------------------------------------------------------------------------
# Raw event handlers
# -------------------------------------------------------------------------

@app.on("meeting.recording.started")
async def on_recording_started(event: Event):
    title = event.payload.get("title", f"Meeting {datetime.now(timezone.utc).strftime('%H:%M')}")
    await app.context.set("app.meeting_in_progress", {"title": title, "started_at": event.payload.get("ts")})
    return {"status": "tracking"}


@app.on("meeting.recording.completed")
async def on_recording_completed(event: Event):
    audio_path = event.payload.get("audio_path", "")
    title = event.payload.get("title", "Meeting")

    if not audio_path or not Path(audio_path).exists():
        return {"transcribed": False, "reason": "audio file not found"}

    transcript = await _transcribe(audio_path)
    if not transcript:
        return {"transcribed": False, "reason": "transcription failed"}

    # Add stress context annotation
    stress_note = ""
    if _stress_level in ("high", "acute"):
        stress_note = f"\n[Context: User was under {_stress_level} stress during this meeting]"

    full_transcript = transcript + stress_note

    # Store in memory
    embedding = await app.llm.embed(full_transcript[:3000])
    summary = await _summarize_meeting(full_transcript)
    action_items = await _extract_action_items(full_transcript)

    item_id = await app.memory.store_knowledge(
        content_type="meeting",
        title=title,
        content=full_transcript,
        summary=summary,
        tags=["meeting", "transcript"],
        embedding=embedding,
    )

    # Also log as life event
    await app.memory.store_life_event(
        event_type="meeting",
        title=title,
        description=summary,
        metadata={"action_items": action_items, "stress_level": _stress_level},
        tags=["meeting"],
        source_app=APP_ID,
    )

    # Publish for downstream (knowledge-base indexing, model updater)
    await app.bus.publish("meeting.recording.processed", {
        "id": item_id,
        "title": title,
        "transcript": full_transcript,
        "summary": summary,
        "action_items": action_items,
        "duration_seconds": event.payload.get("duration_seconds"),
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    await app.context.set("app.meeting_in_progress", None)
    return {
        "transcribed": True,
        "id": item_id,
        "summary": summary,
        "action_items": action_items,
    }


# -------------------------------------------------------------------------
# Actions
# -------------------------------------------------------------------------

@app.action("transcribe_file", description="Transcribe an audio/video file on demand")
async def transcribe_file(params: dict) -> dict:
    audio_path = params.get("path", "")
    if not audio_path:
        return {"error": "path required"}
    transcript = await _transcribe(audio_path)
    return {"transcript": transcript, "length": len(transcript)}


@app.action("search_meetings", description="Search past meeting transcripts")
async def search_meetings(params: dict) -> dict:
    query = params.get("query", "")
    if not query:
        return {"results": [], "error": "query required"}
    embedding = await app.llm.embed(query)
    results = await app.memory.semantic_search(embedding, table="knowledge_items", limit=5)
    # Filter to meeting type
    meeting_results = [r for r in results if "meeting" in r.get("tags", [])]
    return {"query": query, "results": meeting_results}


@app.state
async def get_state() -> dict:
    in_progress = await app.context.get("app.meeting_in_progress")
    return {
        "app_id": APP_ID,
        "meeting_in_progress": bool(in_progress),
        "current_meeting": in_progress,
        "stress_level_at_last_meeting": _stress_level,
    }


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

async def _transcribe(audio_path: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            with open(audio_path, "rb") as f:
                resp = await client.post(
                    f"{WHISPER_URL}/asr",
                    files={"audio_file": f},
                    params={"task": "transcribe", "language": "zh", "output": "txt"},
                )
            resp.raise_for_status()
            return resp.text.strip()
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        return ""


async def _summarize_meeting(transcript: str) -> str:
    return await app.llm.chat(
        f"Summarize this meeting transcript in 3-5 bullet points:\n\n{transcript[:3000]}",
        system="You are a meeting summarizer. Be concise and focus on decisions and key points.",
        max_tokens=300,
    )


async def _extract_action_items(transcript: str) -> list[str]:
    result = await app.llm.chat_json(
        f"Extract action items from this meeting transcript:\n\n{transcript[:2000]}\n\n"
        'Return JSON: {"action_items": ["item1", "item2", ...]}',
    )
    return result.get("action_items", [])


if __name__ == "__main__":
    uvicorn.run(app.build_fastapi(), host="0.0.0.0", port=int(os.getenv("APP_PORT", "8002")))
