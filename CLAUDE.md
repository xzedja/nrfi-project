# CLAUDE.md

## Project Overview

This repo contains a backend service for MLB NRFI/YRFI analytics.

Goals:
- Ingest MLB game and player data into a Postgres database
- Build features for first-inning NRFI prediction
- Train and serve a model that outputs NRFI probabilities and edges vs market odds
- Expose a FastAPI backend that the frontend can call

**Current status:** Full backend is implemented and operational. Historical data backfill (2015–present), feature building, model training, odds ingestion, daily pipeline, and API endpoints are all working.

## Tech Stack

- Python 3.11 (virtual environment at `.venv/`)
- FastAPI for HTTP API
- SQLAlchemy ORM + raw SQL for migrations
- Postgres for data (Docker in dev, managed in prod)
- Docker + docker-compose (`db`, `backend`, `scheduler` services)
- `pybaseball` for Statcast + Fangraphs data
- The Odds API v4 for moneylines and totals
- scikit-learn (logistic regression baseline)
- XGBoost (primary model candidate)
- `python-dotenv` for env var loading

## Repository Structure

- `backend/core/` — configuration (`config.py`), logging
- `backend/db/` — SQLAlchemy models (`models.py`), DB session (`session.py`)
- `backend/data/` — data ingestion and feature building
- `backend/modeling/` — training, evaluation, prediction
- `backend/api/` — FastAPI app and routers
- `scripts/` — one-off and batch scripts (bootstrap, backfill, migrations, daily pipeline)

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
5. When adding new external dependencies, update `requirements.txt`.
6. When adding new DB columns, write a migration script in `scripts/` using `sqlalchemy.text()` and `engine.begin()`. Do not use Alembic yet.
7. Use `python3` or `python` (inside `.venv`) — never assume a bare `python` works system-wide.

## Backend API Framework

We are using FastAPI.

- Main app in `backend/api/main.py`
- Routers in `backend/api/routers/`:
  - `health.py` for `/health`
  - `games.py` for `/games/today` and `/games/{game_id}`
  - `nrfi.py` for `/nrfi/today` and `/nrfi/{game_id}`
- IMPORTANT: register `/nrfi/today` BEFORE `/nrfi/{game_id}` or "today" will be parsed as an int

When adding endpoints:
- Define request/response models with Pydantic
- Use dependency-injected DB sessions from `backend/db/session.py`
- Document endpoints with concise docstrings

## Data and Modeling Scope

The detailed rules for data ingestion and modeling live in `.claude/rules/data-and-model.md`. Follow those when working under `backend/data/` and `backend/modeling/`.

## Completed Implementation

All phases below are done. New work should extend, not rebuild them.

1. ✅ Python environment (`.venv`) and Docker/Postgres running locally
2. ✅ Core config, DB session helpers
3. ✅ SQLAlchemy models for all 6 tables
4. ✅ FastAPI with `/health`, `/games`, `/nrfi` endpoints
5. ✅ Historical backfill (2015–present) via `pybaseball` Statcast
6. ✅ `NrfiFeatures` table with 23 features + trained model
7. ✅ Odds ingestion from The Odds API with P(NRFI) approximation
8. ✅ Daily pipeline (`run_daily.py`) with cron scheduler in Docker
9. ✅ Within-season rolling pitcher stats (last 5 starts ERA/WHIP, first-inning ERA, velocity trend)
10. ✅ XGBoost vs logistic regression comparison in `train_model.py`
