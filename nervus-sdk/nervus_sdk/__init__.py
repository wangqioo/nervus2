"""nervus-sdk v2 — Personal Model-aware app development kit.

Usage:
    from nervus_sdk import NervusApp, Event

    app = NervusApp("my-app")

    @app.on_dimension("stress_indicator")
    async def handle_stress(state: dict, confidence: float):
        if state["level"] == "high":
            # react to high stress ...

    @app.on("health.calorie.meal_logged")
    async def handle_meal(event: Event):
        ...
"""
from .app import NervusApp
from .models import Event, Manifest, DimSubscription
from .bus import SynapseBus
from .context import Context
from .memory import MemoryGraph
from .llm import LLMClient
from .model import PersonalModelClient

__version__ = "2.0.0"
__all__ = [
    "NervusApp",
    "Event",
    "Manifest",
    "DimSubscription",
    "SynapseBus",
    "Context",
    "MemoryGraph",
    "LLMClient",
    "PersonalModelClient",
]
