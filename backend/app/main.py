from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import (
    register_auth_exception_handlers,
    register_chat_exception_handlers,
)
from app.api.routes import (
    auth_router,
    chat_router,
    conversations_router,
    users_router,
)
from app.core.config import settings
from app.db.session import close_db
from app.infra.redis import create_redis_client


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pipeline.agents.workflow import build_workflow

    app.state.redis = None
    if settings.redis_enabled:
        try:
            app.state.redis = await create_redis_client(
                settings.redis_url,
                connect_timeout_seconds=(
                    settings.redis_connect_timeout_seconds
                ),
            )
            logger.info("Redis connected")
        except Exception as exc:
            logger.warning(
                "Redis unavailable; optional features will fail open: %s",
                type(exc).__name__,
            )

    app.state.travel_workflow = build_workflow()
    try:
        yield
    finally:
        redis_client = app.state.redis
        if redis_client is not None:
            await redis_client.aclose()
        await close_db()


app = FastAPI(
    title="Vietnam Travel Advisor API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_auth_exception_handlers(app)
register_chat_exception_handlers(app)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
