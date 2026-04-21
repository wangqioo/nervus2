"""FlowLoader — loads and hot-reloads flow definitions from JSON files."""
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FlowLoader:
    def __init__(self, flows_dir: str):
        self._dir = Path(flows_dir)
        self._flows: list[dict] = []

    def load_all(self) -> int:
        if not self._dir.exists():
            logger.warning("Flows directory not found: %s", self._dir)
            return 0
        loaded = 0
        new_flows = []
        for path in self._dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                flows = data if isinstance(data, list) else data.get("flows", [data])
                for flow in flows:
                    if self._validate(flow, path):
                        new_flows.append(flow)
                        loaded += 1
            except Exception as exc:
                logger.error("Failed to load flow file %s: %s", path, exc)
        self._flows = new_flows
        logger.info("Loaded %d flows from %s", loaded, self._dir)
        return loaded

    def match(self, subject: str, payload: dict) -> list[dict]:
        return [f for f in self._flows if self._matches(f, subject, payload)]

    def list_flows(self) -> list[dict]:
        return [
            {
                "id": f.get("id"),
                "trigger_subject": f.get("trigger", {}).get("subject"),
                "steps": len(f.get("steps", [])),
                "description": f.get("description", ""),
            }
            for f in self._flows
        ]

    def _matches(self, flow: dict, subject: str, payload: dict) -> bool:
        trigger = flow.get("trigger", {})
        pattern = trigger.get("subject", "")
        if not _nats_match(pattern, subject):
            return False
        for key, expected in trigger.get("filter", {}).items():
            actual = payload.get(key)
            if isinstance(actual, list):
                if expected not in actual:
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _validate(flow: dict, path: Path) -> bool:
        required = ("id", "trigger", "steps")
        for field in required:
            if field not in flow:
                logger.warning("Flow in %s missing required field '%s'", path, field)
                return False
        return True


def _nats_match(pattern: str, subject: str) -> bool:
    def match(pat: list, sub: list) -> bool:
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
