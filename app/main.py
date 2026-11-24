"""FastAPI application entrypoint for QueryLens."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import get_logger, setup_logging
from app.services.cache_service import CacheAndTelemetryService
from app.services.nl2sql_agent import NL2SQLAgent

logger = get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    agent: NL2SQLAgent | None = None,
    cache: CacheAndTelemetryService | None = None,
) -> FastAPI:
    """Build and configure the FastAPI application."""
    app_settings = settings or get_settings()
    setup_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = app_settings
        application.state.agent = agent or NL2SQLAgent(settings=app_settings)
        application.state.cache = cache or CacheAndTelemetryService(settings=app_settings)
        logger.info(
            "QueryLens API started",
            extra={
                "extra_data": {
                    "dataset": app_settings.bigquery_dataset,
                    "model": app_settings.llm_model,
                }
            },
        )
        yield

    application = FastAPI(
        title="QueryLens API",
        description="Natural Language Analytics Engine for Google BigQuery Public Datasets",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app = create_app()