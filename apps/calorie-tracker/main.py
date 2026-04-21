"""Calorie Tracker — nervus2 v2 app.

V2 changes vs V1:
- Subscribes to `nutrition_24h` dimension for context-aware meal analysis
- Subscribes to `activity_today` dimension to adjust calorie goals
- Still listens to raw `media.photo.classified` for immediate food detection
- Publishes health events that Model Updater consumes for dimension inference
"""
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

# nervus-sdk v2
import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp, Event

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/data/calorie.db")
APP_ID = "calorie-tracker"

app = NervusApp(
    app_id=APP_ID,
    name="Calorie Tracker",
    description="Photo-to-calorie pipeline with Personal Model integration",
)
app.publishes("health.calorie.meal_logged", "health.calorie.goal_updated")

# -------------------------------------------------------------------------
# Dimension subscriptions (NEW in v2)
# -------------------------------------------------------------------------

@app.on_dimension("nutrition_24h", min_confidence=0.5)
async def on_nutrition_update(state: dict, confidence: float):
    """When Personal Model updates nutrition state, sync local summary."""
    total = state.get("total_calories", 0)
    goal = _get_daily_goal()
    remaining = goal - total
    logger.info(
        "nutrition_24h update: %d kcal consumed, %d remaining (confidence=%.0f%%)",
        total, remaining, confidence * 100,
    )
    _db_exec(
        "INSERT OR REPLACE INTO daily_summary (date, calories_consumed, calories_goal) VALUES (?,?,?)",
        (datetime.now(timezone.utc).date().isoformat(), total, goal),
    )


@app.on_dimension("activity_today", min_confidence=0.5)
async def on_activity_update(state: dict, confidence: float):
    """Adjust calorie goal based on activity level."""
    intensity = state.get("intensity", "sedentary")
    base_goal = int(os.getenv("BASE_CALORIE_GOAL", "2000"))
    bonus = {"sedentary": 0, "light": 150, "moderate": 300, "vigorous": 500}.get(intensity, 0)
    new_goal = base_goal + bonus
    _db_exec(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('daily_goal', ?)",
        (str(new_goal),),
    )
    logger.info("Calorie goal updated to %d kcal (activity: %s)", new_goal, intensity)
    await app.bus.publish("health.calorie.goal_updated", {
        "goal": new_goal,
        "activity_intensity": intensity,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


# -------------------------------------------------------------------------
# Raw event handlers (V1-compatible)
# -------------------------------------------------------------------------

@app.on("media.photo.classified", filter={"tags": "food"})
async def on_food_photo(event: Event):
    """Analyze a classified food photo and log the meal."""
    image_path = event.payload.get("file_path", "")
    if not image_path:
        return {"logged": False, "reason": "no image path"}

    result = await app.llm.vision_json(
        image_path,
        prompt=(
            "Identify the food in this image. "
            "Return JSON: {dish_name, calories_estimate, protein_g, carbs_g, fat_g, confidence}"
        ),
    )
    if not result or result.get("confidence", 0) < 0.5:
        return {"logged": False, "reason": "low confidence identification"}

    # Persist to local SQLite
    _log_meal(result)

    # Publish event for Model Updater to pick up
    await app.bus.publish("health.calorie.meal_logged", {
        "dish_name": result.get("dish_name"),
        "calories": result.get("calories_estimate"),
        "protein_g": result.get("protein_g"),
        "carbs_g": result.get("carbs_g"),
        "fat_g": result.get("fat_g"),
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    # Update context graph for immediate availability
    consumed = _get_consumed_today()
    goal = _get_daily_goal()
    await app.context.set("physical.calorie_remaining", goal - consumed, ttl=3600 * 6)

    return {"logged": True, "dish": result.get("dish_name"), "calories": result.get("calories_estimate")}


# -------------------------------------------------------------------------
# Actions
# -------------------------------------------------------------------------

@app.action("get_daily_summary", description="Return today's calorie summary")
async def get_daily_summary(params: dict) -> dict:
    consumed = _get_consumed_today()
    goal = _get_daily_goal()
    meals = _get_meals_today()
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "calories_consumed": consumed,
        "calories_goal": goal,
        "calories_remaining": goal - consumed,
        "meal_count": len(meals),
        "meals": meals,
    }


@app.action("log_manual_meal", description="Manually log a meal by name")
async def log_manual_meal(params: dict) -> dict:
    dish = params.get("dish_name", "unknown")
    calories = int(params.get("calories", 0))
    if not calories:
        return {"logged": False, "reason": "calories required"}
    _db_exec(
        "INSERT INTO meals (dish_name, calories, protein_g, carbs_g, fat_g, logged_at) VALUES (?,?,?,?,?,?)",
        (dish, calories, params.get("protein_g", 0), params.get("carbs_g", 0),
         params.get("fat_g", 0), datetime.now(timezone.utc).isoformat()),
    )
    await app.bus.publish("health.calorie.meal_logged", {
        "dish_name": dish, "calories": calories,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return {"logged": True, "dish": dish, "calories": calories}


@app.state
async def get_state() -> dict:
    consumed = _get_consumed_today()
    goal = _get_daily_goal()
    return {
        "app_id": APP_ID,
        "calories_consumed_today": consumed,
        "calories_goal": goal,
        "calories_remaining": goal - consumed,
        "meal_count_today": len(_get_meals_today()),
    }


# -------------------------------------------------------------------------
# SQLite helpers
# -------------------------------------------------------------------------

def _init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dish_name TEXT,
            calories REAL,
            protein_g REAL,
            carbs_g REAL,
            fat_g REAL,
            logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS daily_summary (
            date TEXT PRIMARY KEY,
            calories_consumed REAL,
            calories_goal REAL
        );
    """)
    con.commit()
    con.close()


def _db_exec(sql: str, params: tuple = ()):
    con = sqlite3.connect(DB_PATH)
    con.execute(sql, params)
    con.commit()
    con.close()


def _db_query(sql: str, params: tuple = ()) -> list:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows


def _log_meal(result: dict):
    _db_exec(
        "INSERT INTO meals (dish_name, calories, protein_g, carbs_g, fat_g, logged_at) VALUES (?,?,?,?,?,?)",
        (
            result.get("dish_name", "unknown"),
            result.get("calories_estimate", 0),
            result.get("protein_g", 0),
            result.get("carbs_g", 0),
            result.get("fat_g", 0),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _get_consumed_today() -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = _db_query(
        "SELECT SUM(calories) FROM meals WHERE logged_at LIKE ?",
        (f"{today}%",),
    )
    return float(rows[0][0] or 0)


def _get_daily_goal() -> int:
    rows = _db_query("SELECT value FROM settings WHERE key='daily_goal'")
    return int(rows[0][0]) if rows else int(os.getenv("BASE_CALORIE_GOAL", "2000"))


def _get_meals_today() -> list:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = _db_query(
        "SELECT dish_name, calories, logged_at FROM meals WHERE logged_at LIKE ? ORDER BY logged_at",
        (f"{today}%",),
    )
    return [{"dish": r[0], "calories": r[1], "time": r[2][11:16]} for r in rows]


# -------------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    _init_db()
    yield

fastapi_app = app.build_fastapi()
fastapi_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(fastapi_app, host="0.0.0.0", port=int(os.getenv("APP_PORT", "8001")))
