# Backend API Rules

## Scope

These rules apply to:

- `backend/api/**/*`
- Any time we add HTTP endpoints or FastAPI-related code

## Framework

We are using FastAPI.

- Main app in `backend/api/main.py`
- Routers in `backend/api/routers/`

## App Structure

Implement:

1. `backend/api/main.py`
   - Create `FastAPI()` instance.
   - Include routers:
     - `health_router` from `routers/health.py`
     - `games_router` from `routers/games.py`
     - `nrfi_router` from `routers/nrfi.py`
   - Configure basic CORS for the eventual frontend.
   - Add root route `/` that returns a simple JSON message.

2. `backend/api/routers/health.py`
   - Router with:
     - `GET /health`:
       - Returns `{ "status": "ok" }` and optionally DB connectivity info.

3. `backend/api/routers/games.py`
   - Router with endpoints like:
     - `GET /games/today`:
       - Returns basic info for today’s games: game_id, teams, start time.
     - `GET /games/{game_id}`:
       - Returns detail for a single game.

4. `backend/api/routers/nrfi.py`
   - Router with endpoints:
     - `GET /nrfi/{game_id}`:
       - Uses `predict_for_game` to return:
         - `game_id`
         - `p_nrfi_model`
         - `p_nrfi_market` (if available)
         - `edge`
     - `GET /nrfi/today`:
       - Lists predictions for today’s games (joining game listing + prediction).

## API Conventions

- Use Pydantic models for request/response bodies.
- Return JSON with clear field names, e.g.:

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
