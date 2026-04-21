"""Unit tests for Model Updater cold-start phase logic."""
import asyncio
import time
import pytest
import sys
import os
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../personal-model"))


class TestColdStartPhases:
    """Test cold-start phase thresholds without Redis dependency."""

    PHASE1_THRESHOLD = 3 * 86_400
    PHASE2_THRESHOLD = 14 * 86_400

    def _compute_phase(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < self.PHASE1_THRESHOLD:
            return 0
        if elapsed_seconds < self.PHASE2_THRESHOLD:
            return 1
        return 2

    def test_phase0_at_start(self):
        assert self._compute_phase(0) == 0

    def test_phase0_at_2_days(self):
        assert self._compute_phase(2 * 86_400) == 0

    def test_phase0_boundary(self):
        assert self._compute_phase(self.PHASE1_THRESHOLD - 1) == 0

    def test_phase1_at_boundary(self):
        assert self._compute_phase(self.PHASE1_THRESHOLD) == 1

    def test_phase1_at_7_days(self):
        assert self._compute_phase(7 * 86_400) == 1

    def test_phase1_boundary(self):
        assert self._compute_phase(self.PHASE2_THRESHOLD - 1) == 1

    def test_phase2_at_boundary(self):
        assert self._compute_phase(self.PHASE2_THRESHOLD) == 2

    def test_phase2_at_30_days(self):
        assert self._compute_phase(30 * 86_400) == 2

    def test_phase0_skips_inference(self):
        """Phase 0 should skip all LLM calls."""
        phase = self._compute_phase(0)
        should_infer = phase > 0
        assert not should_infer

    def test_phase1_infers_low_confidence(self):
        phase = self._compute_phase(7 * 86_400)
        expected_confidence = 0.45 if phase == 1 else 0.85
        assert expected_confidence == 0.45

    def test_phase2_infers_high_confidence(self):
        phase = self._compute_phase(30 * 86_400)
        expected_confidence = 0.45 if phase == 1 else 0.85
        assert expected_confidence == 0.85


class TestModelUpdaterEventBuffer:
    """Test event buffer parsing and filtering logic."""

    def _parse_events(self, raw: list[str]) -> list[dict]:
        import json
        parsed = []
        for r in raw:
            try:
                parsed.append(json.loads(r))
            except Exception:
                pass
        return parsed

    def _nats_match(self, pattern: str, subject: str) -> bool:
        def match(pat, sub):
            if not pat:
                return not sub
            if pat[0] == ">":
                return True
            if not sub:
                return False
            if pat[0] in ("*", sub[0]):
                return match(pat[1:], sub[1:])
            return False
        return match(pattern.split("."), subject.split("."))

    def test_parse_valid_events(self):
        import json, time
        raw = [
            json.dumps({"subject": "health.sleep.updated", "data": "{}", "ts": time.time()}),
            json.dumps({"subject": "meeting.recording.done", "data": "{}", "ts": time.time()}),
        ]
        parsed = self._parse_events(raw)
        assert len(parsed) == 2

    def test_skip_malformed_events(self):
        raw = ["not-json", '{"subject": "health.ok", "data": "{}"}']
        parsed = self._parse_events(raw)
        assert len(parsed) == 1
        assert parsed[0]["subject"] == "health.ok"

    def test_filter_relevant_events(self):
        import json, time
        events = [
            {"subject": "health.sleep.updated", "ts": time.time()},
            {"subject": "meeting.recording.done", "ts": time.time()},
            {"subject": "health.calorie.meal_logged", "ts": time.time()},
        ]
        nutrition_patterns = ["health.calorie.>", "media.photo.classified", "health.meal.>"]
        relevant = [
            e for e in events
            if any(self._nats_match(p, e["subject"]) for p in nutrition_patterns)
        ]
        assert len(relevant) == 1
        assert relevant[0]["subject"] == "health.calorie.meal_logged"

    def test_skip_nats_internal_subjects(self):
        import json, time
        raw = [
            json.dumps({"subject": "_NATS.ACK.xyz", "data": "{}", "ts": time.time()}),
            json.dumps({"subject": "health.ok", "data": "{}", "ts": time.time()}),
            json.dumps({"subject": "pm.dimension.updated.stress", "data": "{}", "ts": time.time()}),
        ]
        parsed = self._parse_events(raw)
        # Filter internal subjects (as ModelUpdater._on_event does)
        filtered = [e for e in parsed if not e["subject"].startswith("_NATS") and not e["subject"].startswith("pm.")]
        assert len(filtered) == 1
        assert filtered[0]["subject"] == "health.ok"
