"""FastAPI backend server application for Fixate Self-Healing Agent API."""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fixate.api.routes import router as api_router
from fixate.api.websocket import router as stream_router

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
