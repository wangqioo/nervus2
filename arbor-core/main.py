"""Arbor Core v2 — lean fast-routing engine.

V2 philosophy: intelligence lives in the Personal Model, not here.
Arbor Core is now purely a fast event router and app registry.

Removed from v1:
- SemanticRouter (LLM-based routing) — replaced by Personal Model
- DynamicRouter (multi-event correlation) — replaced by Insight Engine
- EmbeddingPipeline — each app handles its own embeddings via SDK

Retained:
- FastRouter: rule-based <100ms routing via flows JSON
- AppRegistry: service discovery, registration, action dispatch
- FlowExecutor: declarative pipeline execution
- Notification system
- mDNS advertisement

V2 additions:
- Dimension Update Dispatcher: fans out Personal Model dim updates to subscribed apps
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.apps_api import router as apps_router
from api.notify_api import router as notify_router
from api.status_api import router as status_router
from router.fast_router import FastRouter
from router.registry import AppRegistry
from executor.flow_executor import FlowExecutor
from executor.flow_loader import FlowLoader
from infra.nats_client import connect as nats_connect, close as nats_close
from infra.redis_client import get_redis
from infra.postgres_client import get_pool, close as pg_close
from infra.dim_dispatcher import DimUpdateDispatcher
import infra.mdns as mdns

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Shared singletons
registry = AppRegistry()
flow_loader = FlowLoader(flows_dir=os.getenv("FLOWS_DIR", "/app/flows"))
executor = FlowExecutor(registry)
fast_router = FastRouter(flow_loader, executor)
dim_dispatcher = DimUpdateDispatcher(registry)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Arbor Core v2 starting")
    nc, _ = await nats_connect()
    await get_redis()
    await get_pool()

    flow_loader.load_all()

    # Subscribe to all app events
    await nc.subscribe(">", cb=fast_router.handle)
    logger.info("Subscribed to all NATS subjects (fast router)")

    # Subscribe to Personal Model dimension updates
    await nc.subscribe("pm.dimension.updated.>", cb=dim_dispatcher.handle)
    logger.info("Subscribed to pm.dimension.updated.> (dim dispatcher)")

    # Advertise via mDNS
    mdns.advertise()

    logger.info("Arbor Core v2 ready on port 8090")
    yield

    logger.info("Arbor Core v2 shutting down")
    mdns.stop()
    await nats_close()
    await pg_close()


app = FastAPI(
    title="Nervus2 Arbor Core",
    version="2.0.0",
    description="Fast event router and app registry for nervus2",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(apps_router)
app.include_router(notify_router)
app.include_router(status_router)

# Expose singletons for API routes
app.state.registry = registry
app.state.flow_loader = flow_loader
app.state.dim_dispatcher = dim_dispatcher


@app.get("/")
async def root():
    return {"service": "nervus2-arbor-core", "version": "2.0.0"}
