"""Unit tests for nervus-sdk v2 models and NATS matching."""
import sys
import os
from unittest.mock import MagicMock

# Stub out runtime dependencies not needed for model tests
for _mod in ("nats", "nats.aio", "nats.aio.client", "nats.js",
             "redis", "redis.asyncio", "asyncpg", "httpx"):
    sys.modules.setdefault(_mod, MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../nervus-sdk"))

from nervus_sdk.models import (
    Event, Manifest, DimSubscription, SubscribeConfig, _nats_match_sdk
)


class TestEvent:
    def test_default_id_generated(self):
        e = Event(subject="health.sleep.updated")
        assert e.id is not None
        assert len(e.id) == 36  # UUID

    def test_default_timestamp(self):
        e = Event(subject="test.event")
        assert e.timestamp is not None

    def test_payload_defaults_empty(self):
        e = Event(subject="test.event")
        assert e.payload == {}

    def test_payload_set(self):
        e = Event(subject="test.event", payload={"key": "value"})
        assert e.payload["key"] == "value"

    def test_correlation_id_optional(self):
        e = Event(subject="test.event")
        assert e.correlation_id is None


class TestManifest:
    def test_minimal_manifest(self):
        m = Manifest(id="test-app", name="Test App")
        assert m.id == "test-app"
        assert m.subscribes == []
        assert m.model_subscriptions == []

    def test_v2_model_subscriptions(self):
        m = Manifest(
            id="stress-app",
            name="Stress App",
            model_subscriptions=[
                DimSubscription(dim_id="stress_indicator", min_confidence=0.6)
            ]
        )
        assert len(m.model_subscriptions) == 1
        assert m.model_subscriptions[0].dim_id == "stress_indicator"
        assert m.model_subscriptions[0].min_confidence == 0.6

    def test_multiple_subscriptions(self):
        m = Manifest(
            id="multi-app",
            name="Multi App",
            model_subscriptions=[
                DimSubscription(dim_id="stress_indicator"),
                DimSubscription(dim_id="nutrition_24h"),
                DimSubscription(dim_id="active_topics"),
            ]
        )
        dim_ids = [s.dim_id for s in m.model_subscriptions]
        assert "stress_indicator" in dim_ids
        assert "nutrition_24h" in dim_ids


class TestDimSubscription:
    def test_defaults(self):
        s = DimSubscription(dim_id="nutrition_24h")
        assert s.handler_path == "/intake/dim_update"
        assert s.min_confidence == 0.5

    def test_custom_confidence(self):
        s = DimSubscription(dim_id="stress_indicator", min_confidence=0.8)
        assert s.min_confidence == 0.8

    def test_confidence_bounds(self):
        import pytest
        with pytest.raises(Exception):
            DimSubscription(dim_id="test", min_confidence=1.5)
        with pytest.raises(Exception):
            DimSubscription(dim_id="test", min_confidence=-0.1)


class TestNatsMatchSdk:
    def test_exact(self):
        assert _nats_match_sdk("health.sleep.updated", "health.sleep.updated")

    def test_no_match(self):
        assert not _nats_match_sdk("health.sleep.updated", "health.sleep.analyzed")

    def test_star_wildcard(self):
        assert _nats_match_sdk("health.*.updated", "health.sleep.updated")
        assert _nats_match_sdk("health.*.updated", "health.calorie.updated")
        assert not _nats_match_sdk("health.*.updated", "health.sleep.deep.updated")

    def test_gt_wildcard(self):
        assert _nats_match_sdk("health.>", "health.sleep.updated")
        assert _nats_match_sdk("health.>", "health.calorie.meal.logged")
        assert not _nats_match_sdk("health.>", "meeting.recording.done")

    def test_full_gt(self):
        assert _nats_match_sdk(">", "anything.at.all")

    def test_empty_subject(self):
        assert not _nats_match_sdk("health.>", "")


class TestSubscribeConfig:
    def test_default_filter(self):
        s = SubscribeConfig(subject="health.>", handler_path="/intake/health")
        assert s.filter == {}

    def test_with_filter(self):
        s = SubscribeConfig(
            subject="media.photo.classified",
            handler_path="/intake/photo",
            filter={"tags": "food"},
        )
        assert s.filter["tags"] == "food"
