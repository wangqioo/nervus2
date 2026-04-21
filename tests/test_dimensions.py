"""Unit tests for dimension registry and NATS matching logic."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../personal-model"))

from model.dimensions import (
    ALL_DIMENSIONS,
    DIM_REGISTRY,
    get_dimension,
    get_dims_for_events,
    _nats_match,
    DimCategory,
    NUTRITION_24H,
    STRESS_INDICATOR,
    UPCOMING_CONTEXT,
)


class TestDimensionRegistry:
    def test_all_dimensions_count(self):
        assert len(ALL_DIMENSIONS) == 20

    def test_dim_registry_keys(self):
        assert len(DIM_REGISTRY) == 20
        assert all(d.id in DIM_REGISTRY for d in ALL_DIMENSIONS)

    def test_get_dimension_found(self):
        dim = get_dimension("nutrition_24h")
        assert dim is not None
        assert dim.id == "nutrition_24h"
        assert dim.category == DimCategory.HEALTH

    def test_get_dimension_not_found(self):
        assert get_dimension("nonexistent_dim") is None

    def test_all_dims_have_required_fields(self):
        for dim in ALL_DIMENSIONS:
            assert dim.id, f"Missing id: {dim}"
            assert dim.name, f"Missing name: {dim.id}"
            assert dim.category, f"Missing category: {dim.id}"
            assert dim.description, f"Missing description: {dim.id}"
            assert len(dim.relevant_events) > 0, f"No events: {dim.id}"
            assert dim.ttl_seconds > 0, f"Invalid TTL: {dim.id}"
            assert dim.inference_prompt, f"Missing prompt: {dim.id}"

    def test_categories_coverage(self):
        cats = {d.category for d in ALL_DIMENSIONS}
        expected = {
            DimCategory.HEALTH, DimCategory.COGNITION, DimCategory.KNOWLEDGE,
            DimCategory.TEMPORAL, DimCategory.SOCIAL, DimCategory.WELLBEING,
        }
        assert cats == expected

    def test_unique_dim_ids(self):
        ids = [d.id for d in ALL_DIMENSIONS]
        assert len(ids) == len(set(ids)), "Duplicate dimension IDs found"


class TestNatsMatching:
    def test_exact_match(self):
        assert _nats_match("health.sleep.updated", "health.sleep.updated")

    def test_wildcard_star_single_token(self):
        assert _nats_match("health.*.updated", "health.sleep.updated")
        assert not _nats_match("health.*.updated", "health.sleep.deep.updated")

    def test_wildcard_gt_suffix(self):
        assert _nats_match("health.>", "health.sleep.updated")
        assert _nats_match("health.>", "health.calorie.meal_logged")
        assert _nats_match("health.>", "health.anything.at.all.levels")
        assert not _nats_match("health.>", "meeting.recording.done")

    def test_no_match(self):
        assert not _nats_match("health.sleep.updated", "health.sleep.analyzed")
        assert not _nats_match("meeting.>", "health.sleep.updated")

    def test_root_gt(self):
        assert _nats_match(">", "any.subject.at.all")
        assert _nats_match(">", "single")

    def test_empty_pattern(self):
        assert not _nats_match("", "something")

    def test_stress_events_match(self):
        for evt in STRESS_INDICATOR.relevant_events:
            # Every declared event should match against itself (no wildcards in input)
            if ">" not in evt and "*" not in evt:
                assert _nats_match(evt, evt)


class TestGetDimsForEvents:
    def test_meal_event_triggers_nutrition(self):
        dims = get_dims_for_events(["health.calorie.meal_logged"])
        dim_ids = [d.id for d in dims]
        assert "nutrition_24h" in dim_ids

    def test_sleep_event_triggers_sleep_dims(self):
        dims = get_dims_for_events(["health.sleep.updated"])
        dim_ids = [d.id for d in dims]
        assert "sleep_last_night" in dim_ids
        assert "sleep_pattern_14d" in dim_ids

    def test_calendar_event_triggers_upcoming(self):
        dims = get_dims_for_events(["calendar.event.created"])
        dim_ids = [d.id for d in dims]
        assert "upcoming_context" in dim_ids

    def test_no_match(self):
        dims = get_dims_for_events(["totally.unknown.subject"])
        assert dims == []

    def test_multiple_events_multiple_dims(self):
        dims = get_dims_for_events([
            "health.sleep.updated",
            "health.calorie.meal_logged",
            "meeting.recording.processed",
        ])
        dim_ids = [d.id for d in dims]
        assert "sleep_last_night" in dim_ids
        assert "nutrition_24h" in dim_ids
        # meeting should trigger cognitive/social dims
        assert len(dim_ids) >= 3

    def test_no_duplicate_dims(self):
        dims = get_dims_for_events(["health.sleep.updated", "health.sleep.analyzed"])
        ids = [d.id for d in dims]
        assert len(ids) == len(set(ids)), "Duplicate dimensions returned"
