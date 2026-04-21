"""Personal Model Service — nervus2 core.

Entry point for the FastAPI application. Mounts all API routers,
starts background workers (Model Updater + Insight Engine) on startup,
and handles graceful shutdown.

Port: 8100
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dimensions_api import router as dims_router, insights_router
from api.query_api import router as query_router
from api.corrections_api import router as corrections_router
from api.status_api import router as status_router
from workers.model_updater import ModelUpdater
from workers.insight_engine import InsightEngine

import infra.nats_client as nats_client
import infra.redis_client as redis_client
import infra.postgres_client as postgres_client
import infra.llm_client as llm_client

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_updater = ModelUpdater()
_insight_engine = InsightEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup ----
    logger.info("Personal Model Service starting up")

    # Connect infrastructure
    await nats_client.connect()
    await redis_client.get_redis()
    await postgres_client.get_pool()

    # Start background workers
    await _updater.start()
    await _insight_engine.start()

    logger.info("Personal Model Service ready on port 8100")
    yield

    # ---- shutdown ----
    logger.info("Personal Model Service shutting down")
    await _updater.stop()
    await _insight_engine.stop()
    await nats_client.close()
    await redis_client.close()
    await postgres_client.close()
    await llm_client.close()
    logger.info("Personal Model Service stopped")


app = FastAPI(
    title="Nervus2 Personal Model",
    version="2.0.0",
    description=(
        "Edge-local personal AI model. "
        "Tracks 20 user dimensions across health, cognition, knowledge, temporal, and social domains."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # mDNS local network — tighten if needed
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(dims_router)
app.include_router(insights_router)
app.include_router(query_router)
app.include_router(corrections_router)
app.include_router(status_router)


@app.get("/")
async def root():
    return {
        "service": "nervus2-personal-model",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
        "status": "/status",
    }
