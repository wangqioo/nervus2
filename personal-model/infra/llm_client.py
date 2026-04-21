"""LLM client — calls local llama.cpp OpenAI-compatible API.

Targets Qwen3.5-4B on Jetson Orin Nano (~2.8 GB VRAM).
Respects the edge constraint: no cloud, all inference local.
"""
import json
import logging
import os
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

LLAMA_URL = os.getenv("LLAMA_URL", "http://localhost:8080")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))

# Token budget for Jetson — Qwen3.5-4B context is 32K but RAM limits us
MAX_PROMPT_TOKENS = int(os.getenv("MAX_PROMPT_TOKENS", "3072"))
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "512"))


class LLMClient:
    def __init__(self):
        self._http = httpx.AsyncClient(
            base_url=LLAMA_URL,
            timeout=LLM_TIMEOUT,
        )

    async def chat(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_tokens: int = MAX_RESPONSE_TOKENS,
        json_mode: bool = False,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": self._truncate(prompt)})

        body: dict[str, Any] = {
            "model": "local",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            resp = await self._http.post("/v1/chat/completions", json=body)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("LLM chat error: %s", exc)
            raise

    async def chat_json(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> dict:
        text = await self.chat(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return self._parse_json(text)

    async def embed(self, text: str) -> list[float]:
        truncated = text[:4000]
        try:
            resp = await self._http.post(
                "/v1/embeddings",
                json={"model": "local", "input": truncated},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except Exception as exc:
            logger.error("LLM embed error: %s", exc)
            raise

    async def close(self) -> None:
        await self._http.aclose()

    def _truncate(self, text: str, max_chars: int = MAX_PROMPT_TOKENS * 3) -> str:
        """Rough token budget enforcement (3 chars ≈ 1 token for Mandarin/English mix)."""
        if len(text) > max_chars:
            logger.debug("Prompt truncated from %d to %d chars", len(text), max_chars)
            return text[:max_chars] + "\n...[truncated]"
        return text

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Extract JSON block from markdown
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Grab first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse JSON from LLM response: %s", text[:200])
        return {}


# Module-level singleton
_client: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


async def close() -> None:
    global _client
    if _client:
        await _client.close()
        _client = None
