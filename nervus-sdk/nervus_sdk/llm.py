"""LLMClient — local Qwen3.5-4B inference via llama.cpp OpenAI-compat API."""
import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

LLAMA_URL = os.getenv("LLAMA_URL", "http://llama:8080")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))


class LLMClient:
    def __init__(self):
        self._http = httpx.AsyncClient(base_url=LLAMA_URL, timeout=TIMEOUT)

    async def chat(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await self._http.post(
            "/v1/chat/completions",
            json={"model": "local", "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def chat_json(self, prompt: str, system: str = "", temperature: float = 0.1) -> dict:
        text = await self.chat(prompt, system=system, temperature=temperature, max_tokens=512)
        return self._extract_json(text)

    async def vision(self, image_path: str, prompt: str) -> str:
        import base64
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}]
        resp = await self._http.post(
            "/v1/chat/completions",
            json={"model": "local", "messages": messages, "max_tokens": 512},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def vision_json(self, image_path: str, prompt: str) -> dict:
        text = await self.vision(image_path, prompt)
        return self._extract_json(text)

    async def embed(self, text: str) -> list[float]:
        resp = await self._http.post(
            "/v1/embeddings",
            json={"model": "local", "input": text[:4000]},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

    async def close(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {}
