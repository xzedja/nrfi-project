# CLAUDE.md

## Project Overview

This repo contains a backend service for MLB NRFI/YRFI analytics.

Goals:
- Ingest MLB game and player data into a Postgres database
- Build features for first-inning NRFI prediction
- Train and serve a model that outputs NRFI probabilities and edges vs market odds
- Expose a FastAPI backend that the frontend can call
- Post daily picks and results to Discord

**Current status:** Full backend is implemented and operational. Historical data backfill (2015–present), feature building, model training, odds ingestion, daily pipeline, Discord integration, and API endpoints are all working. A YRFI heavy-favorite signal has been identified and is tracked separately from model picks.

## Tech Stack

- Python 3.11 (virtual environment at `.venv/`)
- FastAPI for HTTP API
- SQLAlchemy ORM + raw SQL for migrations
- Postgres for data (Docker in dev, managed in prod)
- Docker + docker-compose (`db`, `backend`, `scheduler` services)
- `pybaseball` for Statcast + Fangraphs data
- The Odds API v4 for moneylines and totals
- Open-Meteo archive API for historical weather data
- MLB Stats API for schedule, probable pitchers, umpire assignments
- scikit-learn (logistic regression baseline)
- XGBoost (primary model candidate)
- `python-dotenv` for env var loading

## Repository Structure

- `backend/core/` — configuration (`config.py`), logging
- `backend/db/` — SQLAlchemy models (`models.py`), DB session (`session.py`)
- `backend/data/` — data ingestion and feature building
- `backend/modeling/` — training, evaluation, prediction
- `backend/api/` — FastAPI app and routers
- `scripts/` — one-off and batch scripts (bootstrap, backfill, migrations, daily pipeline, Discord)

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
3. ✅ SQLAlchemy models for all 7 tables (games, pitchers, game_pitchers, team_stats_daily, odds, game_umpires, nrfi_features)
4. ✅ FastAPI with `/health`, `/games`, `/nrfi` endpoints
5. ✅ Historical backfill (2015–present) via `pybaseball` Statcast
6. ✅ `NrfiFeatures` table with 30 features + trained model
7. ✅ Odds ingestion from The Odds API — moneylines, game totals, and first-inning NRFI/YRFI lines via event-specific endpoint
8. ✅ Daily pipeline (`run_daily.py`) with cron scheduler in Docker
9. ✅ Within-season rolling pitcher stats (last 5 starts ERA/WHIP, first-inning ERA, velocity trend, days rest)
10. ✅ XGBoost vs logistic regression comparison in `train_model.py`
11. ✅ Discord integration — daily picks (`post_discord.py`), odds refresh (`refresh_odds.py`), results tracking (`post_results.py`)
12. ✅ Weather features backfilled via Open-Meteo (`backfill_weather.py`)
13. ✅ Umpire assignments + tendency features (`backfill_umpire_assignments.py`, `backfill_ump_features.py`)
14. ✅ Real park factors computed from historical data (`backfill_park_factors.py`)
15. ✅ Automated startup — `entrypoint.sh` bootstraps DB and runs full backfill pipeline on fresh deploy
16. ✅ Nightly game results backfill (`backfill_game_results.py`) — fills first-inning outcomes after games finish
17. ✅ Actual NRFI market odds from The Odds API `totals_1st_1_innings` market (event-specific endpoint); vig-removed implied probability used for `p_nrfi_market`; Poisson approximation as fallback
18. ✅ `p_nrfi_model` stored in `nrfi_features` at pipeline run time for result tracking
19. ✅ Docker container timezone fixed to `America/Los_Angeles` — cron runs at correct local time
20. ✅ Discord picks show pitcher names, NRFI/YRFI odds, game times in ET/CT/PT, and color-coded edge tiers
21. ✅ Pitcher rest days (`home_sp_days_rest`, `away_sp_days_rest`) as model feature; backfilled via `backfill_pitcher_rest.py`
22. ✅ `game_time` stored on `Game` rows and displayed in Discord embeds
23. ✅ YRFI heavy-favorite signal identified — market 60%+ NRFI implied → bet YRFI. Historically +46–54% ROI (2023–2024, 2,700+ bets). Tracked separately in `post_results.py` and displayed as 🔵 blue embeds in Discord picks.
24. ✅ Discord bot (`scripts/discord_bot.py`) with slash commands: `/display-picks`, `/today-record`, `/tomorrow-picks`, `/yrfi-signals`, `/season-record`, `/refresh-odds`, `/yesterday-picks`
25. ✅ Historical odds backfill script (`scripts/backfill_historical_odds.py`) — hybrid approach: actual NRFI lines for recent dates (blended 80/20 with Poisson), Poisson-only for older dates. Costs ~151 API credits/day for actual path. Run when API credits reset.
26. ✅ Lineup OBP features — `home_lineup_obp` / `away_lineup_obp` in `NrfiFeatures`; updated hourly by `refresh_lineups.py` from actual batting orders via MLB Stats API boxscore endpoint. `lineup_obp_diff` (away minus home) is a derived interaction feature in the model.
27. ✅ Dynamic train/calib/val split in `train_model.py` — expanding window based on current date instead of hardcoded years. Constants: `_DATA_START_YEAR=2015`, `_CALIB_WINDOW_DAYS=365`, `_VAL_WINDOW_DAYS=7`. Fit set grows with every passing week; calib set always spans ~1 full prior season for stable Platt scaling.
28. ✅ Weekly automated model retraining — cron fires every Sunday at 8:00 AM (before 8:30 AM daily pipeline) via `start_cron.sh`. Model pkl auto-reloads in `predict.py` on next prediction call after file changes — no container restart needed.
29. ✅ Model metadata saved to `models/nrfi_model.meta.json` after each retrain — training date ranges, game counts, AUC, Brier score per split.
30. ✅ Discord messaging updated — model leans clearly labeled as experimental; YRFI signal retains confident framing with ROI data. Large edges (≥7%) flagged as likely model data issues. Picks sorted by signal tier (🟢→🟡→🔵→🟡→🔴→⚪) then by game time within each tier. Early-season notice explicitly states YRFI signal remains active regardless of model confidence.
31. ✅ Frontend dashboard — team NRFI records (current + prior year with fraction) shown on game cards in a 3-column mini-table alongside 1st-inn R/G.
32. ✅ Frontend dashboard — pitcher NRFI records (current + prior year with fraction) shown at top of PitcherMatchup panel, above L5 ERA stats.
33. ✅ Frontend dashboard — implied NRFI% shown under each bookmaker's odds in OddsTable; best-odds bookmaker sorts first (NRFI-favoring for NRFI picks, YRFI-favoring for YRFI signal picks).
34. ✅ Model training expanded to 2015+ (`_DATA_START_YEAR = 2015`) — 25,564 training rows vs 3,000 previously.
35. ✅ Market-known features removed from `FEATURE_COLS`: `park_factor`, `temperature_f`, `wind_speed_mph`, `wind_out_mph`, `is_dome`, `ump_nrfi_rate_above_avg`, `p_nrfi_market`, `park_x_wind_out`. Model now trained on pre-game knowable features only; `edge` computed at prediction time only.
36. ✅ `home_team_nrfi_rate_l30` / `away_team_nrfi_rate_l30` added as model features — rolling 30-game cross-season NRFI rate per team (min 10 games, else NULL → median-imputed). Migration: `migrate_add_team_nrfi_rate.py`; backfill: `backfill_team_nrfi_rate.py`.
37. ✅ Pick threshold raised 2% → 4% (`VALUE_PLAY_THRESHOLD_PP` env var default changed to `"4"`); `_ANTI_SIGNAL_THRESHOLD` aligned to 7% (above pick threshold) to avoid impossible tier condition.
38. ✅ Current trained model: **XGBoost** (val AUC 0.5698 vs LR 0.5593 on 2,387-game calib set). LR was winner previously; expanded 2015+ dataset gives XGB more signal to learn from.

## Known Gaps (not yet implemented)

- CORS allows all origins (`*`) — tighten when frontend domain is known
- 2025 historical NRFI odds backfill is partial — The Odds API only has first-inning market data for April and July 2025; other months return empty. Backfill was stopped to preserve API credits. Re-run `backfill_historical_odds.py` when credits reset (see below).
- 2025 YRFI signal sample is small (39 bets) — not enough to confirm if edge is holding. Will grow naturally through 2026 live data capture.
- Lineup OBP features are NULL at 8:30 AM pipeline run (lineups not yet posted) — `refresh_lineups.py` fills them in from 10 AM onward. Model uses prior-season median as fallback via `SeasonStartImputer`.
- **Zero-importance feature cleanup (deferred):** 22 of 44 `FEATURE_COLS` show 0.000 importance in both LR and XGBoost: all 12 Fangraphs prior-season pitcher stats (`era`, `fip`, `whip`, `k_pct`, `bb_pct`, `hr9` for home/away SP), team OBP/SLG (home/away), lineup OBP (home/away), and the derived interaction features (`home_sp_era_minus_away`, `lineup_obp_diff`). Removing them would give marginal AUC gain (+0.001–0.003) but requires reworking `SeasonStartImputer.PROXY_MAP`, which currently uses `home_sp_era` as a proxy for `home_sp_last5_era` at season start. Hold until 2–3 weeks of 2026 live data confirms current model improvements are holding.
