"""Unit tests for Arbor Core v2 FlowLoader."""
import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../arbor-core"))

from executor.flow_loader import FlowLoader, _nats_match


SAMPLE_FLOWS = {
    "flows": [
        {
            "id": "test-food-flow",
            "description": "Test flow",
            "trigger": {"subject": "media.photo.classified", "filter": {"tags": "food"}},
            "steps": [
                {"id": "step1", "type": "intake", "params": {"app_id": "calorie-tracker"}}
            ],
        },
        {
            "id": "test-sleep-flow",
            "description": "Sleep flow",
            "trigger": {"subject": "health.sleep.>"},
            "steps": [
                {"id": "step1", "type": "emit_event", "params": {"subject": "health.processed"}}
            ],
        },
    ]
}


@pytest.fixture
def flows_dir():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "core_flows.json"), "w") as f:
            json.dump(SAMPLE_FLOWS, f)
        yield d


class TestFlowLoader:
    def test_load_all(self, flows_dir):
        loader = FlowLoader(flows_dir)
        count = loader.load_all()
        assert count == 2

    def test_match_exact_subject_with_filter(self, flows_dir):
        loader = FlowLoader(flows_dir)
        loader.load_all()
        matched = loader.match("media.photo.classified", {"tags": "food"})
        assert len(matched) == 1
        assert matched[0]["id"] == "test-food-flow"

    def test_no_match_wrong_filter(self, flows_dir):
        loader = FlowLoader(flows_dir)
        loader.load_all()
        matched = loader.match("media.photo.classified", {"tags": "landscape"})
        assert len(matched) == 0

    def test_match_wildcard_subject(self, flows_dir):
        loader = FlowLoader(flows_dir)
        loader.load_all()
        matched = loader.match("health.sleep.updated", {})
        assert any(f["id"] == "test-sleep-flow" for f in matched)

    def test_no_match_unrelated_subject(self, flows_dir):
        loader = FlowLoader(flows_dir)
        loader.load_all()
        matched = loader.match("meeting.recording.done", {})
        assert len(matched) == 0

    def test_list_flows(self, flows_dir):
        loader = FlowLoader(flows_dir)
        loader.load_all()
        flows_list = loader.list_flows()
        assert len(flows_list) == 2
        ids = [f["id"] for f in flows_list]
        assert "test-food-flow" in ids

    def test_invalid_flows_dir(self):
        loader = FlowLoader("/nonexistent/path")
        count = loader.load_all()
        assert count == 0

    def test_malformed_flow_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            # Write a flow missing required fields
            bad = {"flows": [{"id": "bad-flow"}]}  # missing trigger and steps
            with open(os.path.join(d, "bad.json"), "w") as f:
                json.dump(bad, f)
            loader = FlowLoader(d)
            count = loader.load_all()
            assert count == 0

    def test_filter_list_value_match(self, flows_dir):
        loader = FlowLoader(flows_dir)
        loader.load_all()
        # Filter where payload field is a list containing the value
        matched = loader.match("media.photo.classified", {"tags": ["food", "outdoor"]})
        assert len(matched) == 1


class TestFlowLoaderNatsMatch:
    def test_exact(self):
        assert _nats_match("a.b.c", "a.b.c")

    def test_star(self):
        assert _nats_match("a.*.c", "a.b.c")
        assert not _nats_match("a.*.c", "a.b.d")

    def test_gt(self):
        assert _nats_match("a.>", "a.b.c.d")
        assert not _nats_match("a.>", "b.anything")

    def test_full_wildcard(self):
        assert _nats_match(">", "anything.at.all")
