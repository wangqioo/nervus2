"""PersonalModelClient — SDK client for the Personal Model Service.

Allows apps to:
- Read any dimension's current state
- Submit natural language queries
- Submit corrections
- Query recent insights
"""
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

PERSONAL_MODEL_URL = os.getenv("PERSONAL_MODEL_URL", "http://personal-model:8100")
CLIENT_TIMEOUT = float(os.getenv("PM_CLIENT_TIMEOUT", "10"))


class PersonalModelClient:
    def __init__(self, base_url: str = PERSONAL_MODEL_URL):
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._base, timeout=CLIENT_TIMEOUT)

    async def get_dimension(self, dim_id: str) -> Optional[dict]:
        """Get a single dimension's current state."""
        try:
            r = await self._http.get(f"/dimensions/{dim_id}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.error("PersonalModelClient.get_dimension(%s): %s", dim_id, exc)
            return None

    async def get_all_dimensions(self, category: Optional[str] = None) -> list[dict]:
        """List all dimensions (optionally filtered by category)."""
        params = {}
        if category:
            params["category"] = category
        try:
            r = await self._http.get("/dimensions", params=params)
            r.raise_for_status()
            return r.json().get("dimensions", [])
        except Exception as exc:
            logger.error("PersonalModelClient.get_all_dimensions: %s", exc)
            return []

    async def query(self, question: str, include_insights: bool = True) -> Optional[dict]:
        """Natural language question answered from the Personal Model."""
        try:
            r = await self._http.post(
                "/query",
                json={"question": question, "include_insights": include_insights},
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.error("PersonalModelClient.query: %s", exc)
            return None

    async def submit_correction(
        self,
        dim_id: str,
        corrected_value: dict[str, Any],
        note: str = "",
    ) -> bool:
        """Submit a user correction for a dimension."""
        try:
            r = await self._http.post(
                "/corrections",
                json={"dim_id": dim_id, "corrected_value": corrected_value, "note": note},
            )
            r.raise_for_status()
            return r.json().get("accepted", False)
        except Exception as exc:
            logger.error("PersonalModelClient.submit_correction(%s): %s", dim_id, exc)
            return False

    async def get_insights(self, limit: int = 10) -> list[dict]:
        """Return recent cross-dimensional insights."""
        try:
            r = await self._http.get("/insights", params={"limit": limit})
            r.raise_for_status()
            return r.json().get("insights", [])
        except Exception as exc:
            logger.error("PersonalModelClient.get_insights: %s", exc)
            return []

    async def get_dimension_history(
        self,
        dim_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """Return time-series history for a dimension."""
        try:
            r = await self._http.get(
                f"/dimensions/{dim_id}/history",
                params={"limit": limit},
            )
            r.raise_for_status()
            return r.json().get("history", [])
        except Exception as exc:
            logger.error("PersonalModelClient.get_dimension_history(%s): %s", dim_id, exc)
            return []

    async def close(self) -> None:
        await self._http.aclose()
