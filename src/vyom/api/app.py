"""Vyom FastAPI application factory.

Responsibilities:
  - Create the FastAPI app with metadata
  - Add CORS middleware (restricts origins in production via VYOM_CORS_ORIGINS)
  - Add rate limiting via slowapi
  - Register all routers
  - Manage the DB connection pool lifecycle (open on startup, close on shutdown)

The app is created by calling create_app(). The module-level `app` object is
used by uvicorn locally and by Mangum (lambda_handler.py) on AWS Lambda.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from vyom.api.deps import get_pool
from vyom.api.routers import feedback, health, ingest, query
from vyom.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def _configure_event_logger(event_log_path: str) -> None:
    """Structured per-request JSON events (see query.py's _log_completion)
    go to a dedicated logger/file, deliberately separate from the human-
    readable app log above — a CloudWatch metric filter needs each line to
    parse as pure JSON, which the normal timestamp/level/name-prefixed
    format would break. See infra/main.tf for the CloudWatch Agent config
    that tails this same path."""
    path = Path(event_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    event_logger = logging.getLogger("vyom.events")
    event_logger.setLevel(logging.INFO)
    event_logger.propagate = False  # don't also duplicate into the app log above

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    event_logger.addHandler(handler)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the DB pool on startup, close it on shutdown."""
    logger.info("Vyom starting — warming DB connection pool …")
    await get_pool()
    logger.info("DB pool ready")
    yield
    logger.info("Vyom shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_event_logger(settings.event_log_path)

    app = FastAPI(
        title="Vyom API",
        version="1.0.0",
        description=(
            "Multi-source agentic RAG over Indian fintech data — "
            "BSE filings, SEBI circulars, RBI macro data"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — allow the Next.js frontend and any additional origins from config
    origins = [o.strip() for o in settings.cors_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(ingest.router)
    app.include_router(feedback.router)

    return app


# Module-level app instance used by uvicorn and Mangum
app = create_app()