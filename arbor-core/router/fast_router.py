"""FastRouter — rule-based event router, <100ms target.

Matches incoming NATS events against flow definitions.
Hands off to FlowExecutor when a flow matches.
No LLM calls — pure pattern matching.
"""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class FastRouter:
    def __init__(self, flow_loader, executor):
        self._loader = flow_loader
        self._executor = executor

    async def handle(self, msg) -> bool:
        subject = msg.subject
        if subject.startswith("_NATS") or subject.startswith("pm."):
            return False

        try:
            payload = json.loads(msg.data.decode("utf-8", errors="replace"))
        except Exception:
            payload = {"raw": msg.data.decode("utf-8", errors="replace")}

        event = {"subject": subject, "payload": payload}

        matched_flows = self._loader.match(subject, payload)
        if not matched_flows:
            return False

        for flow in matched_flows:
            asyncio.create_task(self._executor.execute(flow, event))

        return True
