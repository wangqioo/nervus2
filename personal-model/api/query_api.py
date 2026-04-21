"""POST /query — natural language cross-dimensional question answering.

Gathers all populated dimension states, builds a rich context, and asks
the local LLM to answer the user's question in plain language.

Example queries:
  - "Why am I feeling tired today?"
  - "What should I focus on this afternoon?"
  - "How is my health trend this week?"
  - "Am I spending enough time on learning?"
"""
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from infra.llm_client import get_llm
from model.state import get_all_states
from model.snapshot import get_recent_insights

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

SYSTEM_PROMPT = """\
You are the personal AI advisor for a single user. You have access to their
current personal model — a set of inferred dimensions about their health,
cognition, knowledge, habits, and social life.

Answer the user's question directly and helpfully. Be specific, use the data
from their dimensions. Acknowledge low-confidence data appropriately.
Keep your answer concise (2-4 sentences) unless more detail is needed.
Do not make up data that isn't in the provided dimensions."""


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    include_insights: bool = True


class QueryResponse(BaseModel):
    answer: str
    dimensions_used: list[str]
    confidence: str  # 'high' | 'medium' | 'low'
    context_snapshot: dict


@router.post("", response_model=QueryResponse)
async def query_model(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    all_states = await get_all_states()
    populated = {k: v for k, v in all_states.items() if v is not None}

    if not populated:
        return QueryResponse(
            answer=(
                "Your personal model hasn't collected enough data yet. "
                "Keep using your apps and I'll have more to share soon."
            ),
            dimensions_used=[],
            confidence="low",
            context_snapshot={},
        )

    # Build dimension context
    dim_ctx_lines = []
    for dim_id, state in sorted(populated.items()):
        val = state.current_value
        summary = val.get("summary") if isinstance(val, dict) else None
        if not summary:
            summary = json.dumps(val)[:300]
        conf = f"{state.confidence:.0%}"
        dim_ctx_lines.append(f"  [{dim_id}] ({conf} confidence): {summary}")

    dim_context = "\n".join(dim_ctx_lines)

    # Optionally include recent insights
    insights_ctx = ""
    if req.include_insights:
        insights = await get_recent_insights(limit=5)
        if insights:
            lines = [f"  - {i['description']}" for i in insights]
            insights_ctx = "\nRecent cross-dimensional insights:\n" + "\n".join(lines)

    prompt = (
        f"User's Personal Model — current dimensions:\n{dim_context}"
        f"{insights_ctx}\n\n"
        f"User question: {req.question}"
    )

    llm = get_llm()
    try:
        answer = await llm.chat(prompt, system=SYSTEM_PROMPT, temperature=0.3, max_tokens=400)
    except Exception as exc:
        logger.error("Query LLM error: %s", exc)
        raise HTTPException(status_code=503, detail="LLM unavailable")

    # Determine overall confidence based on populated dimensions
    avg_conf = sum(s.confidence for s in populated.values()) / len(populated)
    confidence_label = "high" if avg_conf > 0.7 else ("medium" if avg_conf > 0.4 else "low")

    return QueryResponse(
        answer=answer.strip(),
        dimensions_used=list(populated.keys()),
        confidence=confidence_label,
        context_snapshot={
            "populated_dimensions": len(populated),
            "total_dimensions": 20,
            "avg_confidence": round(avg_conf, 2),
        },
    )
