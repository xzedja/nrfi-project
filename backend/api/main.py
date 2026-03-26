"""
backend/api/main.py

FastAPI application entry point.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import health, games, nrfi

app = FastAPI(
    title="NRFI Analytics API",
    description="MLB first-inning run prediction and edge analysis.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten this when the frontend domain is known
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(games.router)
app.include_router(nrfi.router)


@app.get("/")
def root():
    return {"message": "NRFI Analytics API", "docs": "/docs"}
