"""Personal Model dimension registry — 20 dimensions across 5 categories.

Each DimensionDefinition declares:
- id, name, category, description
- relevant_events: NATS subject patterns that can update this dimension
- ttl_seconds: how long current state stays valid in Redis before considered stale
- inference_prompt: template injected into Model Updater LLM call
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DimCategory(str, Enum):
    HEALTH = "health"
    COGNITION = "cognition"
    KNOWLEDGE = "knowledge"
    TEMPORAL = "temporal"
    SOCIAL = "social"
    WELLBEING = "wellbeing"


@dataclass
class DimensionDefinition:
    id: str
    name: str
    category: DimCategory
    description: str
    relevant_events: list[str]   # NATS subject patterns (wildcard ok)
    ttl_seconds: int             # staleness window for Redis current state
    inference_prompt: str        # inserted into LLM system prompt during update


# ---------------------------------------------------------------------------
# Health (4 dimensions)
# ---------------------------------------------------------------------------

NUTRITION_24H = DimensionDefinition(
    id="nutrition_24h",
    name="24h Nutrition",
    category=DimCategory.HEALTH,
    description="Caloric intake, macronutrients, and meal quality for the last 24 hours.",
    relevant_events=["health.calorie.>", "media.photo.classified", "health.meal.>"],
    ttl_seconds=86_400,   # 24h
    inference_prompt=(
        "Based on the provided events, infer the user's nutritional state for the last 24 hours. "
        "Return JSON with keys: total_calories (int), protein_g (float), carbs_g (float), "
        "fat_g (float), meal_count (int), quality_score (0-10), summary (str ≤40 chars)."
    ),
)

SLEEP_LAST_NIGHT = DimensionDefinition(
    id="sleep_last_night",
    name="Last Night Sleep",
    category=DimCategory.HEALTH,
    description="Sleep duration and quality from the most recent night.",
    relevant_events=["health.sleep.>", "sense.sleep.>"],
    ttl_seconds=86_400,
    inference_prompt=(
        "Infer last night's sleep from the events. "
        "Return JSON: duration_hours (float), quality_score (0-10), "
        "interruptions (int), bedtime (HH:MM or null), wake_time (HH:MM or null), summary (str ≤40 chars)."
    ),
)

SLEEP_PATTERN_14D = DimensionDefinition(
    id="sleep_pattern_14d",
    name="14-Day Sleep Pattern",
    category=DimCategory.HEALTH,
    description="Trend and regularity of sleep over the last two weeks.",
    relevant_events=["health.sleep.>", "sense.sleep.>"],
    ttl_seconds=3_600 * 6,   # update less frequently — pattern changes slowly
    inference_prompt=(
        "Infer the 14-day sleep pattern. "
        "Return JSON: avg_duration_hours (float), regularity_score (0-10), "
        "trend ('improving'|'stable'|'declining'), deficit_hours (float), summary (str ≤40 chars)."
    ),
)

ACTIVITY_TODAY = DimensionDefinition(
    id="activity_today",
    name="Activity Today",
    category=DimCategory.HEALTH,
    description="Physical activity, steps, and movement intensity today.",
    relevant_events=["health.activity.>", "sense.activity.>", "sense.steps.>"],
    ttl_seconds=3_600 * 3,
    inference_prompt=(
        "Infer today's physical activity. "
        "Return JSON: steps (int), active_minutes (int), intensity ('sedentary'|'light'|'moderate'|'vigorous'), "
        "goal_met (bool), summary (str ≤40 chars)."
    ),
)

# ---------------------------------------------------------------------------
# Cognition (4 dimensions)
# ---------------------------------------------------------------------------

COGNITIVE_LOAD_NOW = DimensionDefinition(
    id="cognitive_load_now",
    name="Current Cognitive Load",
    category=DimCategory.COGNITION,
    description="Estimated current mental load based on task switching, meetings, and notifications.",
    relevant_events=[
        "meeting.>", "calendar.event.>", "system.notification.>",
        "context.task.>", "sense.app_usage.>",
    ],
    ttl_seconds=3_600,   # 1h — changes quickly
    inference_prompt=(
        "Infer the user's current cognitive load. "
        "Return JSON: level ('low'|'medium'|'high'|'overloaded'), score (0-10), "
        "primary_stressor (str ≤60 chars or null), summary (str ≤40 chars)."
    ),
)

FOCUS_QUALITY_TODAY = DimensionDefinition(
    id="focus_quality_today",
    name="Today's Focus Quality",
    category=DimCategory.COGNITION,
    description="Quality and depth of focused/deep work accomplished today.",
    relevant_events=["sense.app_usage.>", "context.focus.>", "sense.screen.>"],
    ttl_seconds=3_600 * 6,
    inference_prompt=(
        "Infer today's focus quality. "
        "Return JSON: deep_work_minutes (int), interruptions (int), "
        "quality_score (0-10), peak_focus_window (str ≤30 chars or null), summary (str ≤40 chars)."
    ),
)

STRESS_INDICATOR = DimensionDefinition(
    id="stress_indicator",
    name="Stress Indicator",
    category=DimCategory.COGNITION,
    description="Current stress level inferred from behavioral, physiological, and contextual signals.",
    relevant_events=[
        "health.hrv.>", "sense.typing_cadence.>", "meeting.>",
        "calendar.event.>", "health.sleep.>",
    ],
    ttl_seconds=3_600 * 2,
    inference_prompt=(
        "Infer the user's current stress level. "
        "Return JSON: level ('calm'|'mild'|'moderate'|'high'|'acute'), score (0-10), "
        "likely_cause (str ≤80 chars or null), summary (str ≤40 chars)."
    ),
)

ENERGY_LEVEL_NOW = DimensionDefinition(
    id="energy_level_now",
    name="Current Energy Level",
    category=DimCategory.COGNITION,
    description="Subjective and inferred energy level right now.",
    relevant_events=[
        "health.sleep.>", "health.meal.>", "health.activity.>",
        "sense.typing_cadence.>",
    ],
    ttl_seconds=3_600 * 2,
    inference_prompt=(
        "Infer the user's current energy level. "
        "Return JSON: level ('depleted'|'low'|'moderate'|'high'|'peak'), score (0-10), "
        "contributing_factors (list[str]), summary (str ≤40 chars)."
    ),
)

# ---------------------------------------------------------------------------
# Knowledge (3 dimensions)
# ---------------------------------------------------------------------------

ACTIVE_TOPICS = DimensionDefinition(
    id="active_topics",
    name="Active Learning Topics",
    category=DimCategory.KNOWLEDGE,
    description="Topics the user is currently exploring or learning about.",
    relevant_events=[
        "knowledge.article.>", "knowledge.pdf.>", "knowledge.video.>",
        "media.reading.>", "knowledge.note.>",
    ],
    ttl_seconds=3_600 * 24,
    inference_prompt=(
        "Identify the user's active learning topics from the events. "
        "Return JSON: topics (list[{name:str, intensity:'casual'|'active'|'deep_dive', "
        "recent_sources:int}]), primary_topic (str or null), summary (str ≤40 chars)."
    ),
)

KNOWLEDGE_GRAPH_STATE = DimensionDefinition(
    id="knowledge_graph_state",
    name="Knowledge Graph State",
    category=DimCategory.KNOWLEDGE,
    description="Overview of connected concepts being built in the knowledge base.",
    relevant_events=["knowledge.>"],
    ttl_seconds=3_600 * 12,
    inference_prompt=(
        "Summarize the current state of the user's knowledge graph. "
        "Return JSON: total_nodes (int), active_clusters (list[str]), "
        "newest_cluster (str or null), growth_rate ('slow'|'moderate'|'fast'), summary (str ≤40 chars)."
    ),
)

READING_VELOCITY = DimensionDefinition(
    id="reading_velocity",
    name="Reading Velocity",
    category=DimCategory.KNOWLEDGE,
    description="Rate and type of content being consumed.",
    relevant_events=[
        "knowledge.article.>", "knowledge.pdf.>", "media.reading.>", "rss.article.>",
    ],
    ttl_seconds=3_600 * 24,
    inference_prompt=(
        "Infer the user's recent reading velocity. "
        "Return JSON: articles_7d (int), pdfs_7d (int), "
        "dominant_format ('articles'|'pdfs'|'books'|'mixed'), "
        "velocity_trend ('decreasing'|'stable'|'increasing'), summary (str ≤40 chars)."
    ),
)

# ---------------------------------------------------------------------------
# Temporal / Behavioral (4 dimensions)
# ---------------------------------------------------------------------------

DAILY_ROUTINE = DimensionDefinition(
    id="daily_routine",
    name="Daily Routine",
    category=DimCategory.TEMPORAL,
    description="Detected daily behavioral pattern — when user wakes, works, eats, sleeps.",
    relevant_events=[
        "health.sleep.>", "health.meal.>", "calendar.event.>",
        "sense.app_usage.>", "health.activity.>",
    ],
    ttl_seconds=3_600 * 6,
    inference_prompt=(
        "Infer the user's typical daily routine from multi-day event patterns. "
        "Return JSON: wake_time (HH:MM or null), sleep_time (HH:MM or null), "
        "peak_productivity_window (str ≤30 chars or null), meal_regularity_score (0-10), "
        "routine_consistency_score (0-10), summary (str ≤40 chars)."
    ),
)

WEEKLY_PATTERN = DimensionDefinition(
    id="weekly_pattern",
    name="Weekly Behavioral Pattern",
    category=DimCategory.TEMPORAL,
    description="Which days of the week are most productive, social, restful, etc.",
    relevant_events=[
        "calendar.event.>", "meeting.>", "health.activity.>",
        "sense.app_usage.>",
    ],
    ttl_seconds=3_600 * 24,
    inference_prompt=(
        "Infer the user's weekly behavioral pattern. "
        "Return JSON: busiest_days (list[str]), restful_days (list[str]), "
        "social_days (list[str]), pattern_stability ('erratic'|'moderate'|'consistent'), "
        "summary (str ≤40 chars)."
    ),
)

UPCOMING_CONTEXT = DimensionDefinition(
    id="upcoming_context",
    name="Upcoming Context",
    category=DimCategory.TEMPORAL,
    description="What is coming up in the next 24 hours — meetings, deadlines, events.",
    relevant_events=["calendar.event.>", "reminder.>", "schedule.>"],
    ttl_seconds=3_600,   # 1h — needs to be fresh
    inference_prompt=(
        "Summarize the user's upcoming schedule for the next 24 hours. "
        "Return JSON: event_count (int), next_event_name (str or null), "
        "next_event_in_minutes (int or null), meeting_heavy (bool), "
        "free_blocks (int), summary (str ≤40 chars)."
    ),
)

LOCATION_CONTEXT = DimensionDefinition(
    id="location_context",
    name="Current Location Context",
    category=DimCategory.TEMPORAL,
    description="Whether user is home, at work, traveling, or elsewhere.",
    relevant_events=["sense.location.>", "travel.>"],
    ttl_seconds=3_600 * 4,
    inference_prompt=(
        "Infer the user's current location context. "
        "Return JSON: context ('home'|'work'|'commute'|'travel'|'unknown'), "
        "travel_active (bool), city (str or null), summary (str ≤40 chars)."
    ),
)

# ---------------------------------------------------------------------------
# Social (3 dimensions)
# ---------------------------------------------------------------------------

SOCIAL_RHYTHM = DimensionDefinition(
    id="social_rhythm",
    name="Social Rhythm",
    category=DimCategory.SOCIAL,
    description="Frequency and quality of social interactions recently.",
    relevant_events=["meeting.>", "sense.communication.>", "calendar.event.>"],
    ttl_seconds=3_600 * 12,
    inference_prompt=(
        "Infer the user's social rhythm for the last 7 days. "
        "Return JSON: interaction_frequency ('isolated'|'low'|'moderate'|'high'), "
        "meeting_count_7d (int), async_comms_count_7d (int), "
        "social_satisfaction_inferred (0-10), summary (str ≤40 chars)."
    ),
)

KEY_RELATIONSHIPS = DimensionDefinition(
    id="key_relationships",
    name="Key Relationships",
    category=DimCategory.SOCIAL,
    description="Most recently active relationships and contact patterns.",
    relevant_events=["meeting.>", "sense.communication.>"],
    ttl_seconds=3_600 * 24,
    inference_prompt=(
        "Identify the user's most recently active relationships. "
        "Return JSON: active_contacts (list[{name:str, interaction_count_7d:int, "
        "last_interaction:'today'|'yesterday'|'this_week'|'older'}]), "
        "summary (str ≤40 chars)."
    ),
)

COMMUNICATION_LOAD = DimensionDefinition(
    id="communication_load",
    name="Communication Load",
    category=DimCategory.SOCIAL,
    description="Volume of messages, emails, and meetings demanding attention.",
    relevant_events=["sense.communication.>", "meeting.>", "calendar.event.>"],
    ttl_seconds=3_600 * 2,
    inference_prompt=(
        "Infer the user's current communication load. "
        "Return JSON: level ('light'|'normal'|'heavy'|'overwhelming'), "
        "pending_replies (int or null), meetings_today (int), "
        "async_messages_today (int), summary (str ≤40 chars)."
    ),
)

# ---------------------------------------------------------------------------
# Wellbeing (2 dimensions)
# ---------------------------------------------------------------------------

MOOD_INDICATOR = DimensionDefinition(
    id="mood_indicator",
    name="Mood Indicator",
    category=DimCategory.WELLBEING,
    description="Inferred current emotional/mood state.",
    relevant_events=[
        "health.sleep.>", "health.activity.>", "sense.typing_cadence.>",
        "calendar.event.>", "meeting.>",
    ],
    ttl_seconds=3_600 * 3,
    inference_prompt=(
        "Infer the user's current mood. "
        "Return JSON: mood ('very_negative'|'negative'|'neutral'|'positive'|'very_positive'), "
        "score (-5 to 5), confidence_note (str ≤60 chars), summary (str ≤40 chars)."
    ),
)

LIFE_SATISFACTION_TREND = DimensionDefinition(
    id="life_satisfaction_trend",
    name="Life Satisfaction Trend",
    category=DimCategory.WELLBEING,
    description="14-day trend in overall life satisfaction inferred from behavioral signals.",
    relevant_events=["health.>", "meeting.>", "knowledge.>", "sense.>"],
    ttl_seconds=3_600 * 24,
    inference_prompt=(
        "Infer the user's 14-day life satisfaction trend from behavioral signals. "
        "Return JSON: trend ('declining'|'stable'|'improving'), score (0-10), "
        "strongest_positive_signal (str ≤80 chars or null), "
        "strongest_negative_signal (str ≤80 chars or null), summary (str ≤40 chars)."
    ),
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_DIMENSIONS: list[DimensionDefinition] = [
    # Health
    NUTRITION_24H, SLEEP_LAST_NIGHT, SLEEP_PATTERN_14D, ACTIVITY_TODAY,
    # Cognition
    COGNITIVE_LOAD_NOW, FOCUS_QUALITY_TODAY, STRESS_INDICATOR, ENERGY_LEVEL_NOW,
    # Knowledge
    ACTIVE_TOPICS, KNOWLEDGE_GRAPH_STATE, READING_VELOCITY,
    # Temporal
    DAILY_ROUTINE, WEEKLY_PATTERN, UPCOMING_CONTEXT, LOCATION_CONTEXT,
    # Social
    SOCIAL_RHYTHM, KEY_RELATIONSHIPS, COMMUNICATION_LOAD,
    # Wellbeing
    MOOD_INDICATOR, LIFE_SATISFACTION_TREND,
]

DIM_REGISTRY: dict[str, DimensionDefinition] = {d.id: d for d in ALL_DIMENSIONS}


def get_dimension(dim_id: str) -> Optional[DimensionDefinition]:
    return DIM_REGISTRY.get(dim_id)


def get_dims_for_events(subjects: list[str]) -> list[DimensionDefinition]:
    """Return dimensions whose relevant_events overlap with the given NATS subjects."""
    result = []
    for dim in ALL_DIMENSIONS:
        for pattern in dim.relevant_events:
            for subject in subjects:
                if _nats_match(pattern, subject):
                    result.append(dim)
                    break
            else:
                continue
            break
    return result


def _nats_match(pattern: str, subject: str) -> bool:
    """NATS wildcard matching: '>' matches any suffix, '*' matches single token."""
    pat_parts = pattern.split(".")
    sub_parts = subject.split(".")
    return _match_parts(pat_parts, sub_parts)


def _match_parts(pat: list[str], sub: list[str]) -> bool:
    if not pat:
        return not sub
    if pat[0] == ">":
        return True
    if not sub:
        return False
    if pat[0] == "*" or pat[0] == sub[0]:
        return _match_parts(pat[1:], sub[1:])
    return False
