"""
PhysioBot - AI Physiotherapy Robot Assistant
FastAPI application entry point.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.routers import session as session_router
from app.routers import voice as voice_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    logger.info("PhysioBot starting up…")
    logger.info("Cyberwave base URL : %s", settings.cyberwave_base_url)
    logger.info("Camera index       : %d", settings.camera_index)
    yield
    logger.info("PhysioBot shutting down.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PhysioBot",
    description="AI physiotherapy coaching system — robot arm demo + VLM evaluation + voice feedback",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the browser frontend (served on same origin) and any local dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(session_router.router, prefix="/api/session", tags=["session"])
app.include_router(voice_router.router, prefix="/api/voice", tags=["voice"])

# ---------------------------------------------------------------------------
# Static files  (index.html + app.js)
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Root — serve the frontend SPA
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse("static/index.html")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    """Return service liveness status."""
    return {"status": "ok", "service": "physiobot"}


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
