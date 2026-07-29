"""FastAPI backend server application for Fixate Self-Healing Agent API."""

import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from fixate.api.routes import router as api_router
from fixate.api.websocket import router as stream_router
from fixate.paths import DASHBOARD_DIR

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fixate Self-Healing Agent API",
    description="Backend API for orchestrating self-healing CI pipeline, RAG, and telemetry streaming",
    version="0.1.0",
)

# Enable CORS for React frontend dashboard (Vite default port 5173 / localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(stream_router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "fixate-api", "version": "0.1.0"}


# Serve built frontend production static files if dashboard/dist directory exists
static_dir = str(DASHBOARD_DIR / "dist")
if os.path.exists(static_dir):
    logger.info(f"Mounting production static frontend from {static_dir}")
    assets_dir = os.path.join(static_dir, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="static_assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        # Unmatched API routes must 404. Returning None here rendered them as a
        # JSON `null` with status 200, so a client could not tell a missing
        # endpoint from an empty result.
        if full_path.startswith(("api", "ws")):
            raise HTTPException(status_code=404, detail=f"No such endpoint: /{full_path}")

        file_path = os.path.join(static_dir, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(static_dir, "index.html"))
