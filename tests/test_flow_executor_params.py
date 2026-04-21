"""Unit tests for FlowExecutor JSONPath parameter resolution."""
import sys
import os
import pytest
from unittest.mock import MagicMock

# Stub out runtime dependencies not needed for param resolution tests
for _mod in ("nats", "nats.aio", "nats.aio.client", "nats.js",
             "redis", "redis.asyncio", "asyncpg", "httpx",
             "zeroconf"):
    sys.modules.setdefault(_mod, MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../arbor-core"))

from executor.flow_executor import FlowExecutor


class TestResolveParams:
    def _resolve(self, params, ctx):
        return FlowExecutor._resolve_params(params, ctx)

    def _jsonpath(self, path, ctx):
        return FlowExecutor._jsonpath(path, ctx)

    def test_simple_jsonpath(self):
        ctx = {"trigger": {"payload": {"file_path": "/tmp/photo.jpg"}}}
        result = self._jsonpath("$.trigger.payload.file_path", ctx)
        assert result == "/tmp/photo.jpg"

    def test_nested_jsonpath(self):
        ctx = {"step1": {"result": {"id": "abc-123"}}}
        result = self._jsonpath("$.step1.result.id", ctx)
        assert result == "abc-123"

    def test_missing_path_returns_none(self):
        ctx = {"trigger": {"payload": {}}}
        result = self._jsonpath("$.trigger.payload.nonexistent", ctx)
        assert result is None

    def test_resolve_params_with_jsonpath(self):
        ctx = {"trigger": {"payload": {"calories": 450}}}
        params = {"app_id": "calorie-tracker", "calories": "$.trigger.payload.calories"}
        resolved = self._resolve(params, ctx)
        assert resolved["app_id"] == "calorie-tracker"
        assert resolved["calories"] == 450

    def test_resolve_params_static_values(self):
        ctx = {}
        params = {"key": "static_value", "count": 42}
        resolved = self._resolve(params, ctx)
        assert resolved["key"] == "static_value"
        assert resolved["count"] == 42

    def test_resolve_nested_params(self):
        ctx = {"trigger": {"payload": {"title": "Meeting Alpha"}}}
        params = {
            "outer": {
                "inner": "$.trigger.payload.title"
            }
        }
        resolved = self._resolve(params, ctx)
        assert resolved["outer"]["inner"] == "Meeting Alpha"

    def test_resolve_missing_path_returns_none(self):
        ctx = {}
        params = {"value": "$.missing.path"}
        resolved = self._resolve(params, ctx)
        assert resolved["value"] is None
