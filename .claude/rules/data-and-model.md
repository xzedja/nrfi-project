# Data and Modeling Rules

## Scope

These rules apply when editing files under:

- `backend/data/**/*`
- `backend/modeling/**/*`
- `scripts/backfill_history.py`
- `scripts/bootstrap_db.py`
- `backend/db/**/*` (for schema work that affects data/modeling)

## Data Sources

Use:

- `pybaseball` for historical MLB stats and game logs[web:48][web:51]
- An MLB odds API (e.g. The Odds API) for market odds[web:27][web:41]

Assume:
- API keys are provided via env vars:
  - `ODDS_API_KEY`
- DB connection via `DATABASE_URL` env var.

Do not add scraping logic from HTML sites unless explicitly asked.

## Database Schema (First Version)

Define these SQLAlchemy models in `backend/db/models.py`:

1. `Game`
   - `id` (PK, integer or UUID)
   - `external_id` (optional, provider game id)
   - `game_date` (date)
   - `home_team` (string)
   - `away_team` (string)
   - `inning_1_home_runs` (int)
   - `inning_1_away_runs` (int)
   - `nrfi` (bool)
   - `park` (string or park id)

2. `Pitcher`
   - `id` (PK)
   - `external_id` (int or string, as used by pybaseball)
   - `name`
   - `throws` (L/R)
   - other basic fields as needed

3. `GamePitchers`
   - `id` (PK)
   - `game_id` (FK → Game)
   - `home_sp_id` (FK → Pitcher)
   - `away_sp_id` (FK → Pitcher)

4. `TeamStatsDaily`
   - `id` (PK)
   - `team`
   - `date`
   - `obp`
   - `slg`
   - `ops`
   - `first_inning_runs_scored_per_game`
   - `first_inning_runs_allowed_per_game`
   - other aggregations as needed later

5. `Odds`
   - `id` (PK)
   - `game_id` (FK → Game)
   - `source`
   - `market` (e.g., 'ml', 'total', 'nrfi' if available)
   - `home_ml`
   - `away_ml`
   - `total`
   - `total_over_odds`
   - `total_under_odds`
   - `fetched_at` (datetime)

6. `NrfiFeatures`
   - `id` (PK)
   - `game_id` (FK → Game)
   - one column per feature used for modeling (numeric, bool)
   - `nrfi_label` (bool, same as Game.nrfi, duplicated for modeling convenience)
   - optional: `p_nrfi_market` (float) as precomputed implied probability

When asked to extend schema, add fields and migrations rather than breaking changes.

## Data Ingestion Steps

Implement these scripts/modules:

1. `backend/core/config.py`
   - Load `DATABASE_URL`, `ODDS_API_KEY`, and other settings from env.
   - Provide a Config object or functions to access.

2. `backend/db/session.py`
   - Create SQLAlchemy engine and sessionmaker from `DATABASE_URL`.
   - Provide `get_db()` dependency for FastAPI.

3. `scripts/bootstrap_db.py`
   - Use models and engine to create all tables.
   - Safe to run multiple times (no errors if tables exist).

4. `backend/data/fetch_stats.py`
   - Functions using `pybaseball` to:
     - Pull pitching stats for a season range (e.g. 2018–2024).
     - Pull batting stats for a season range.
     - Pull game logs including inning-by-inning line scores if available.
   - Provide helpers:
     - `load_games_for_season(season: int)` → list of game dicts with teams, date, inning scores.
     - `load_starting_pitchers_for_season(season: int)` → mapping of game → starting pitcher ids.

5. `scripts/backfill_history.py`
   - For a given season range:
     - Call `fetch_stats` helpers.
     - Insert/update:
       - `Game` rows with 1st-inning runs and `nrfi` label: `nrfi = (inning_1_home_runs == 0 and inning_1_away_runs == 0)`.
       - `Pitcher` rows (deduplicated by external id).
       - `GamePitchers` rows linking starting pitchers to games.
   - Make idempotent by checking for existing `Game.external_id` or `(game_date, home_team, away_team)` before insert.

6. `backend/data/build_features.py`
   - Build team-level daily stats into `TeamStatsDaily`:
     - Based on batting and pitching stats up to each date.
   - For each `Game`:
     - Join `Game`, `GamePitchers`, `TeamStatsDaily`, and simple park factor.
     - Compute feature columns:
       - Starter ERA, WHIP, K%, BB%, HR/9
       - Team OBP/SLG/OPS
       - First-inning run rates
       - Simple park factor
     - Insert into `NrfiFeatures` with `nrfi_label`.

## Odds and Edge Calculation

In `backend/data/fetch_odds.py`:

- Implement a client for MLB odds API:
  - Fetch upcoming games and odds.
  - Map odds to `Game` via teams and start time.
  - Insert into `Odds` table.

- Provide functions to:
  - Convert American or decimal odds to implied probabilities.
  - Approximate NRFI implied probability from totals and moneylines if direct NRFI market is not available (simple heuristic at first).

In `build_features.py` or a separate helper:

- For each game with odds, compute and store `p_nrfi_market` in `NrfiFeatures` when possible.

## Modeling Rules

In `backend/modeling/`:

1. `train_model.py`
   - Load `NrfiFeatures` rows for past seasons.
   - Use only features available before first pitch (no post-game stats).
   - Split data chronologically into train/validation/test.
   - Train a baseline model (e.g. logistic regression or XGBoost) predicting `nrfi_label`.
   - Evaluate using:
     - AUC, log loss
     - Brier score for calibration
   - Save model artifact via `model_store.py`.

2. `model_store.py`
   - Provide `save_model(model, path)` and `load_model(path)` helpers.

3. `predict.py`
   - Provide functions:
     - `predict_for_game(game_id)`:
       - Load features from `NrfiFeatures`.
       - Load model.
       - Compute `p_nrfi_model`.
       - Pull `p_nrfi_market` from features or `Odds` if available.
       - Compute `edge = p_nrfi_model - p_nrfi_market`.
       - Return a dict suitable for API responses.

4. `evaluate_model.py`
   - Optional: additional reporting, calibration plots, and backtest metrics.

## Anti-Leakage Rules

- Do NOT use any stats from after the game date when building features for that game.
- When aggregating team stats, use only data up to (date - 1).
- When approximating market probabilities, only use odds that would have been known before game start.

If there is any ambiguity, default to the safer “no leakage” choice.
