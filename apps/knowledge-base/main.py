"""Knowledge Base — nervus2 v2 app.

V2 changes vs V1:
- Subscribes to `active_topics` dimension to prioritize indexing
- Subscribes to `cognitive_load_now` to throttle heavy indexing during peak load
- Publishes knowledge events consumed by Model Updater for dimension updates
"""
import logging
import os
import sys
from datetime import datetime, timezone

import uvicorn

sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, Event

logger = logging.getLogger(__name__)
APP_ID = "knowledge-base"

app = NervusApp(
    app_id=APP_ID,
    name="Knowledge Base",
    description="Semantic knowledge store with Personal Model topic awareness",
)
app.publishes(
    "knowledge.article.indexed",
    "knowledge.pdf.indexed",
    "knowledge.query.answered",
)

# -------------------------------------------------------------------------
# Dimension subscriptions
# -------------------------------------------------------------------------

_current_load = "low"
_active_topics: list[str] = []


@app.on_dimension("active_topics", min_confidence=0.5)
async def on_active_topics(state: dict, confidence: float):
    """Track what the user is actively learning to boost related content."""
    global _active_topics
    topics = state.get("topics", [])
    _active_topics = [t.get("name", "") for t in topics if isinstance(t, dict)]
    primary = state.get("primary_topic")
    logger.info("Active topics updated: %s (primary: %s)", _active_topics, primary)


@app.on_dimension("cognitive_load_now", min_confidence=0.6)
async def on_cognitive_load(state: dict, confidence: float):
    """Throttle background indexing when user is overloaded."""
    global _current_load
    _current_load = state.get("level", "low")
    if _current_load in ("high", "overloaded"):
        logger.info("Cognitive load is %s — pausing heavy indexing", _current_load)


# -------------------------------------------------------------------------
# Raw event handlers
# -------------------------------------------------------------------------

@app.on("knowledge.article.>")
async def on_article(event: Event):
    if _current_load in ("high", "overloaded"):
        logger.debug("Skipping article indexing — cognitive load: %s", _current_load)
        return {"indexed": False, "reason": "cognitive_load_high"}
    return await _index_content(event, "article")


@app.on("knowledge.pdf.>")
async def on_pdf(event: Event):
    return await _index_content(event, "pdf")


@app.on("knowledge.note.>")
async def on_note(event: Event):
    return await _index_content(event, "note")


@app.on("knowledge.video.>")
async def on_video(event: Event):
    return await _index_content(event, "video")


@app.on("meeting.recording.processed")
async def on_meeting(event: Event):
    transcript = event.payload.get("transcript", "")
    if not transcript:
        return {"indexed": False}
    title = event.payload.get("title", f"Meeting {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")
    embedding = await app.llm.embed(transcript[:3000])
    item_id = await app.memory.store_knowledge(
        content_type="meeting",
        title=title,
        content=transcript,
        summary=await _summarize(transcript),
        tags=["meeting"],
        embedding=embedding,
    )
    await app.bus.publish("knowledge.meeting.indexed", {"id": item_id, "title": title})
    return {"indexed": True, "id": item_id}


# -------------------------------------------------------------------------
# Actions
# -------------------------------------------------------------------------

@app.action("semantic_search", description="Search the knowledge base by natural language query")
async def semantic_search(params: dict) -> dict:
    query = params.get("query", "")
    if not query:
        return {"results": [], "error": "query required"}
    limit = int(params.get("limit", 5))
    embedding = await app.llm.embed(query)
    results = await app.memory.semantic_search(embedding, table="knowledge_items", limit=limit)
    return {"query": query, "results": results, "count": len(results)}


@app.action("ask", description="Answer a question using the knowledge base (RAG)")
async def ask(params: dict) -> dict:
    question = params.get("question", "")
    if not question:
        return {"answer": "", "error": "question required"}

    # Retrieve relevant context
    embedding = await app.llm.embed(question)
    results = await app.memory.semantic_search(embedding, limit=3)

    if not results:
        return {"answer": "No relevant knowledge found.", "sources": []}

    context = "\n\n".join([
        f"[{r['title']}]: {r.get('summary', '')}" for r in results
    ])

    # Add active topic hint
    topic_hint = ""
    if _active_topics:
        topic_hint = f"\nUser is currently focused on: {', '.join(_active_topics[:3])}"

    answer = await app.llm.chat(
        f"Context:\n{context}{topic_hint}\n\nQuestion: {question}",
        system=(
            "You are a personal knowledge assistant. "
            "Answer based only on the provided context. "
            "Be concise and cite sources when relevant."
        ),
        max_tokens=400,
    )

    await app.bus.publish("knowledge.query.answered", {
        "question": question,
        "sources": [r["title"] for r in results],
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "answer": answer,
        "sources": [{"title": r["title"], "similarity": r["similarity"]} for r in results],
    }


@app.action("get_topic_summary", description="Summarize knowledge on a specific topic")
async def get_topic_summary(params: dict) -> dict:
    topic = params.get("topic", "")
    if not topic:
        return {"summary": "", "error": "topic required"}
    embedding = await app.llm.embed(topic)
    results = await app.memory.semantic_search(embedding, limit=5)
    if not results:
        return {"topic": topic, "item_count": 0, "summary": "No knowledge on this topic yet."}
    context = "\n".join([f"- {r['title']}: {r.get('summary', '')}" for r in results])
    summary = await app.llm.chat(
        f"Summarize what we know about '{topic}':\n{context}",
        max_tokens=300,
    )
    return {"topic": topic, "item_count": len(results), "summary": summary}


@app.state
async def get_state() -> dict:
    return {
        "app_id": APP_ID,
        "active_topics": _active_topics,
        "cognitive_load": _current_load,
        "indexing_paused": _current_load in ("high", "overloaded"),
    }


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

async def _index_content(event: Event, content_type: str) -> dict:
    payload = event.payload
    title = payload.get("title", payload.get("filename", "Untitled"))
    content = payload.get("content", payload.get("text", ""))
    url = payload.get("url", payload.get("source_url", ""))
    tags = payload.get("tags", [])

    # Add active topics as tags
    if _active_topics:
        tags = list(set(tags + _active_topics[:3]))

    if not content:
        return {"indexed": False, "reason": "no content"}

    summary = await _summarize(content[:2000])
    embedding = await app.llm.embed(f"{title} {summary}")

    item_id = await app.memory.store_knowledge(
        content_type=content_type,
        title=title,
        content=content[:5000],
        summary=summary,
        source_url=url,
        tags=tags,
        embedding=embedding,
    )

    await app.bus.publish(f"knowledge.{content_type}.indexed", {
        "id": item_id, "title": title, "tags": tags,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {"indexed": True, "id": item_id, "title": title}


async def _summarize(text: str, max_len: int = 2000) -> str:
    if len(text) < 200:
        return text
    try:
        return await app.llm.chat(
            f"Summarize in 2-3 sentences:\n{text[:max_len]}",
            max_tokens=150,
        )
    except Exception:
        return text[:300]


if __name__ == "__main__":
    uvicorn.run(app.build_fastapi(), host="0.0.0.0", port=int(os.getenv("APP_PORT", "8004")))
