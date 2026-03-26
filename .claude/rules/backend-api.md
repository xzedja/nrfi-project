# Backend API Rules

## Scope

These rules apply to:

- `backend/api/**/*`
- Any time we add HTTP endpoints or FastAPI-related code

## Framework

We are using FastAPI.

- Main app in `backend/api/main.py`
- Routers in `backend/api/routers/`

## App Structure (Implemented)

All endpoints below are live.

1. `backend/api/main.py`
   - Creates `FastAPI()` instance with CORS middleware (allow all origins for dev).
   - Includes `health_router`, `games_router`, `nrfi_router`.
   - Root route `/` returns `{"message": "NRFI API"}`.

2. `backend/api/routers/health.py`
   - `GET /health` — runs `SELECT 1` to verify DB connectivity, returns `{"status": "ok"}`.

3. `backend/api/routers/games.py`
   - `GET /games/today` — returns games for today from the DB.
   - `GET /games/{game_id}` — returns detail for a single game.

4. `backend/api/routers/nrfi.py`
   - `GET /nrfi/today` — returns predictions for all of today's games.
   - `GET /nrfi/{game_id}` — returns prediction for a single game (404 if not found).
   - **IMPORTANT:** `/nrfi/today` is registered BEFORE `/{game_id}` to prevent "today" being parsed as an integer.

## API Response Format

```json
{
  "game_id": 123,
  "home_team": "LAD",
  "away_team": "SF",
  "game_date": "2026-04-02",
  "p_nrfi_model": 0.61,
  "p_nrfi_market": 0.55,
  "edge": 0.06
}
```

- `p_nrfi_model` — model's probability that no run scores in the first inning
- `p_nrfi_market` — implied P(NRFI) derived from game total via Poisson approximation
- `edge` — `p_nrfi_model - p_nrfi_market` (positive = model thinks NRFI is more likely than market implies)

## API Conventions

- Use Pydantic models for request/response bodies.
- Use dependency-injected DB sessions from `backend/db/session.py` (`get_db()`).
- Return 404 with a clear message if a resource is not found.
- Document endpoints with concise docstrings.
- Predictions route through `backend/modeling/predict.py` (`predict_for_game`, `predict_for_today`).
