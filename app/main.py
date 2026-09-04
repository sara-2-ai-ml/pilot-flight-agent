"""FastAPI application entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import Settings, get_settings
from app.core.errors import DEFAULT_USER_ERROR_MESSAGE, AgentFailure
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RateLimitMiddleware, TraceMiddleware
from app.core.tracing import generate_trace_id, get_trace_id


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown hooks."""
    settings: Settings = app.state.settings
    setup_logging(settings.log_level)

    logger = get_logger("main")
    logger.info(
        "application_started",
        extra={
            "event": "application_started",
            "app_name": settings.app_name,
            "tools_mode": settings.tools_mode.value,
            "nlu_use_mock": settings.nlu_use_mock,
            "planner_use_mock": settings.planner_use_mock,
            "env_NLU_USE_MOCK": os.environ.get("NLU_USE_MOCK"),
        },
    )

    from app.agent.workers import configure_worker_registry

    configure_worker_registry(settings)

    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    resolved = settings or get_settings()

    app = FastAPI(
        title=resolved.app_name,
        debug=resolved.debug,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    origins = [origin.strip() for origin in resolved.cors_origins.split(",") if origin.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(TraceMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.include_router(api_router)

    @app.exception_handler(AgentFailure)
    async def agent_failure_handler(_request: Request, exc: AgentFailure) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": exc.message, "trace_id": exc.trace_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        trace_id = get_trace_id() or generate_trace_id()
        logger = get_logger("main")
        logger.exception(
            "unhandled_error",
            extra={"trace_id": trace_id, "event": "unhandled_error", "error": str(exc)},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": DEFAULT_USER_ERROR_MESSAGE, "trace_id": trace_id},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run("app.main:app", host=cfg.host, port=cfg.port, reload=cfg.debug)
