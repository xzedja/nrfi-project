# CLAUDE.md

## Project Overview

This repo contains a backend service for MLB NRFI/YRFI analytics.

Goals:
- Ingest MLB game and player data into a Postgres database
- Build features for first-inning NRFI prediction
- Train and serve a model that outputs NRFI probabilities and edges vs market odds
- Expose a FastAPI backend that the frontend can call

We are starting with:
- Historical data via `pybaseball` (free MLB stats tools)[web:48][web:51]
- Odds via a public MLB odds API (e.g. The Odds API)[web:27][web:41]
- A single NRFI probability model

## Tech Stack

- Python 3.x
- FastAPI for HTTP API
- SQLAlchemy for ORM
- Alembic for migrations (later)
- Postgres for data (Docker in dev, managed in prod)
- Docker + docker-compose

## Repository Structure

Follow this structure:

- `backend/core`: configuration, logging, shared utilities
- `backend/db`: SQLAlchemy models, DB session helpers, migrations
- `backend/data`: raw data ingestion and feature building
- `backend/modeling`: training, evaluation, prediction utilities
- `backend/api`: FastAPI app and routers
- `scripts`: one-off or batch scripts (bootstrap, backfill)

When adding new backend functionality, prefer placing it into one of these existing modules.

## General Rules for Claude

When you (Claude) modify or add code in this repo:

1. Respect the directory structure above; do not invent new top-level folders without a clear reason.
2. Never hard-code secrets or API keys. Always read them from environment variables via `backend/core/config.py`.
3. Prefer small, single-responsibility modules:
   - Data ingestion belongs in `backend/data/`
   - DB schema in `backend/db/`
   - Modeling code in `backend/modeling/`
   - HTTP endpoints in `backend/api/` and `backend/api/routers/`
4. Keep code Pythonic and type-annotated where practical.
5. When adding new external dependencies, update `pyproject.toml` or `requirements.txt`.

## Backend API Framework

We are using FastAPI.

- Create a single FastAPI app in `backend/api/main.py`
- Use routers under `backend/api/routers/`:
  - `health.py` for `/health`
  - `games.py` for game listing endpoints
  - `nrfi.py` for NRFI prediction endpoints

When adding endpoints:
- Define request/response models with Pydantic
- Use dependency-injected DB sessions from `backend/db/session.py`
- Document endpoints with concise docstrings

## Data and Modeling Scope

The detailed rules for data ingestion and modeling live in `.claude/rules/data-and-model.md`. Follow those when working under `backend/data/` and `backend/modeling/`.

## Next Steps for the Project

The first implementation phases:

1. Bootstrap Python environment and Docker/Postgres locally.
2. Implement core config and DB session helpers.
3. Define SQLAlchemy models for games, pitchers, odds, features.
4. Implement a basic `/health` endpoint with FastAPI.
5. Implement historical data backfill with `pybaseball`.
6. Build an initial `nrfi_features` table and a baseline model.

When I ask you for help (Claude), focus on moving these steps forward incrementally rather than trying to do everything at once.
