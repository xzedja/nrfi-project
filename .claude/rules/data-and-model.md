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

- `pybaseball` for historical MLB stats and game logs
  - `pybaseball.statcast()` for pitch-by-pitch Statcast data
  - `pybaseball.pitching_stats()` for Fangraphs season leaderboard stats
  - `pybaseball.playerid_reverse_lookup()` for MLB ID → Fangraphs ID mapping
  - Fangraphs uses column `IDfg` (NOT `playerid`) for pitcher IDs
- The Odds API v4 for market odds (`https://api.the-odds-api.com/v4/`)
- MLB Stats API (`https://statsapi.mlb.com/api/v1/schedule`) for daily schedule + probable pitchers

Assume:
- API keys via env vars: `ODDS_API_KEY`
- DB connection via `DATABASE_URL` env var

Do not add scraping logic from HTML sites unless explicitly asked.

## Database Schema (Current)

All models are defined in `backend/db/models.py`.

1. `Game` (`games` table)
   - `id`, `external_id` (MLB game_pk, unique), `game_date`, `home_team`, `away_team`
   - `inning_1_home_runs`, `inning_1_away_runs`, `nrfi` (bool)
   - `park`, `game_number` (1 or 2 for doubleheaders)
   - No unique constraint on (game_date, home_team, away_team) — dropped to support doubleheaders

2. `Pitcher` (`pitchers` table)
   - `id`, `external_id` (MLB MLBAM ID, unique), `name`, `throws` (L/R)

3. `GamePitchers` (`game_pitchers` table)
   - `id`, `game_id` (FK), `home_sp_id` (FK → Pitcher), `away_sp_id` (FK → Pitcher)

4. `TeamStatsDaily` (`team_stats_daily` table)
   - `id`, `team`, `date`, `obp`, `slg`, `ops`
   - `first_inning_runs_scored_per_game`, `first_inning_runs_allowed_per_game`
   - Unique constraint on (team, date)

5. `Odds` (`odds` table)
   - `id`, `game_id` (FK), `source`, `market`, `home_ml`, `away_ml`
   - `total`, `total_over_odds`, `total_under_odds`, `fetched_at`

6. `NrfiFeatures` (`nrfi_features` table)
   - `id`, `game_id` (FK, unique)
   - **Prior-season Fangraphs stats** (home and away SP):
     - `home_sp_era`, `home_sp_whip`, `home_sp_k_pct`, `home_sp_bb_pct`, `home_sp_hr9`
     - `away_sp_era`, `away_sp_whip`, `away_sp_k_pct`, `away_sp_bb_pct`, `away_sp_hr9`
     - K% and BB% are stored as decimals (0–1 scale from Fangraphs)
   - **Within-season rolling stats** (last 5 starts, pre-game only, from Statcast):
     - `home_sp_last5_era`, `home_sp_last5_whip` — ERA/WHIP proxy over last 5 starts
     - `home_sp_first_inn_era` — first-inning ERA proxy, all prior starts this season
     - `home_sp_avg_velo` — mean fastball velocity over last 5 starts
     - `home_sp_velo_trend` — last-start avg velo minus 5-start avg (negative = declining)
     - Same 5 columns for `away_sp_*`
   - **Team offense**:
     - `home_team_first_inn_runs_per_game`, `away_team_first_inn_runs_per_game`
   - `park_factor` (currently 1.0 placeholder)
   - `nrfi_label` (bool), `p_nrfi_market` (float)

When extending the schema, add columns via a migration script in `scripts/` using `sqlalchemy.text()` and `engine.begin()`. Do not use Alembic yet.

## Key Implementation Files

### `backend/data/fetch_stats.py`
- `_STATCAST_COLS` — columns kept from Statcast responses. Includes `release_speed` and `events` (needed for rolling velocity + WHIP features).
- `_season_cache` — in-process dict to avoid re-fetching Statcast data within the same Python process.
- `_fetch_statcast_season(season)` — fetches Statcast in ~4-week chunks, uses disk cache via `pybaseball.cache.enable()`. Season start is **April 1** (not March 20) to exclude spring training.
- `load_games_for_season(season)` — returns list of game dicts with first-inning run counts and NRFI label.
- `load_starting_pitchers_for_season(season)` — returns dict of game_pk → home/away SP MLBAM IDs.
- SP identification: pitcher of the first pitch in Top of 1st = home SP; first pitch in Bot of 1st = away SP.

### `backend/data/build_features.py`
- Imports `_fetch_statcast_season` from `fetch_stats.py` to share the in-process cache.
- `_load_sp_stats(season, pitcher_mlb_ids)` — Fangraphs prior-season stats. Uses `IDfg` column (not `playerid`). Missing pitchers get league-median values.
- `_precompute_team_stats(db, season)` — rolling first-inning run rates from the games table, using only games before each target date.
- `_precompute_pitcher_starts(season_df)` — groups Statcast data by pitcher + game_pk to compute per-start stats: `first_inn_runs`, `ip_half` (half-innings pitched), `hits_walks`, `runs_allowed`, `avg_velo`.
- `_pitcher_rolling_features(starts_df, before_date, n=5)` — computes last-n-starts ERA proxy, WHIP proxy, first-inning ERA, avg velocity, and velocity trend from the per-start DataFrame.
- `build_features_for_season(season)` — main entry point, idempotent (skips existing rows).

### `backend/data/fetch_today.py`
- Fetches today's schedule + probable starters from MLB Stats API.
- Filters to game types R/P/F/D/L/W (skips spring training type S).

### `backend/data/fetch_odds.py`
- `_TEAM_NAME_TO_ABBREV` — maps The Odds API full team names → Statcast abbreviations.
- `estimate_p_nrfi_from_total(total)` — Poisson approximation: `λ = (total/18) × 0.74`, `P(NRFI) = e^(-2λ)`. Calibrated so total=8.5 → P(NRFI)≈0.50.
- `_extract_best_markets()` — uses preferred bookmaker (DraftKings) but falls back to other bookmakers if totals are missing.
- Game matching uses a **±1 day window** to handle UTC vs local date mismatches (e.g. Tokyo Series games).

### `scripts/run_daily.py`
Daily pipeline (runs at 9:03 AM via Docker cron scheduler):
1. `fetch_schedule(target)` — MLB Stats API schedule + probable pitchers
2. Insert `Game` + `GamePitchers` rows (idempotent)
3. `build_features_for_season(season)` — builds NrfiFeatures for new games
4. `fetch_and_store_odds(date_str)` — odds ingestion (non-fatal if fails)

### `scripts/start_cron.sh`
- Dumps container env vars to `/etc/environment` so cron jobs can access `DATABASE_URL` etc.
- Installs crontab: `3 9 * * *` → runs `run_daily.py`

## Modeling Rules

### Current feature set (23 features in `FEATURE_COLS`)
See `backend/modeling/train_model.py` for the full list.

### `train_model.py`
- Trains **both** logistic regression (LR) and XGBoost (XGB), prints side-by-side metrics.
- Saves whichever model wins on **validation AUC**.
- Chronological 80/10/10 train/val/test split (no shuffling).
- LR pipeline: `SimpleImputer(median)` → `StandardScaler` → `LogisticRegression(max_iter=1000)`
- XGB pipeline: `SimpleImputer(median)` → `XGBClassifier` with strong regularisation to prevent overfitting:
  - `max_depth=3`, `min_child_weight=80`, `gamma=1.0`, `reg_alpha=0.5`, `reg_lambda=5.0`
- Evaluates AUC, log loss, Brier score on all three splits.
- Logs LR feature coefficients and XGB feature importances.

### `model_store.py`
- `save_model(model, path)` and `load_model(path)` via pickle.
- Default path: `models/nrfi_model.pkl`

### `predict.py`
- Module-level `_model` cache to avoid reloading on every request.
- `predict_for_game(game_id, db)` — returns `p_nrfi_model`, `p_nrfi_market`, `edge`.
- `predict_for_today(db)` — returns predictions for all today's games.

## Anti-Leakage Rules

- Do NOT use any stats from after the game date when building features for that game.
- When aggregating team stats, use only data from games with `date < game_date`.
- When computing rolling pitcher stats, use only starts with `game_date < target_game_date`.
- When approximating market probabilities, only use odds that would have been known before game start.
- Prior-season Fangraphs stats use `season - 1` to ensure no in-season leakage.

If there is any ambiguity, default to the safer "no leakage" choice.

## DB Migration Pattern

When adding new columns to existing tables:

```python
from sqlalchemy import text
from backend.db.session import engine

with engine.begin() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'table_name'"
    ))
    existing = {row[0] for row in result}
    if "new_column" not in existing:
        conn.execute(text("ALTER TABLE table_name ADD COLUMN new_column DOUBLE PRECISION"))
```

See `scripts/migrate_add_rolling_features.py` for a complete example.
