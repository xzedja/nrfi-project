# Data and Modeling Rules

## Scope

These rules apply when editing files under:

- `backend/data/**/*`
- `backend/modeling/**/*`
- `scripts/backfill_*.py`
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
- MLB Stats API (`https://statsapi.mlb.com/api/v1/schedule`) for daily schedule, probable pitchers, umpire assignments
- Open-Meteo archive API for historical weather data (free, no key required)

Assume:
- API keys via env vars: `ODDS_API_KEY`
- DB connection via `DATABASE_URL` env var

Do not add scraping logic from HTML sites unless explicitly asked.

## Database Schema (Current)

All models are defined in `backend/db/models.py`.

1. `Game` (`games` table)
   - `id`, `external_id` (MLB game_pk, unique), `game_date`, `game_time` (ISO UTC string, e.g. "2026-04-01T23:10:00Z"), `home_team`, `away_team`
   - `inning_1_home_runs`, `inning_1_away_runs`, `nrfi` (bool)
   - `park`, `game_number` (1 or 2 for doubleheaders)
   - No unique constraint on (game_date, home_team, away_team) — dropped to support doubleheaders
   - `game_time` is patched for existing rows in `run_daily.py` if it was previously NULL

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
   - `first_inn_over_odds` (YRFI American odds), `first_inn_under_odds` (NRFI American odds)
   - No unique constraint — upsert logic in `fetch_odds.py` queries by `(game_id, source)` before inserting

6. `GameUmpire` (`game_umpires` table)
   - `id`, `game_id` (FK, unique), `ump_id` (MLB person ID), `ump_name`
   - Populated going forward by `run_daily.py` and historically by `backfill_umpire_assignments.py`

7. `NrfiFeatures` (`nrfi_features` table)
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
     - `home_sp_days_rest` — days since pitcher's most recent prior start (NULL = first start of season)
     - Same 6 columns for `away_sp_*`
   - **Team offense**:
     - `home_team_first_inn_runs_per_game`, `away_team_first_inn_runs_per_game`
   - **Park**: `park_factor` — computed from historical first-inning run rates (prior seasons only). Regressed toward 1.0 based on sample size (`min(1.0, games / 200)`).
   - **Weather** (NULL for dome parks):
     - `temperature_f`, `wind_speed_mph`, `wind_out_mph` (positive = blowing toward CF), `is_dome`
   - **Umpire**: `ump_nrfi_rate_above_avg` — HP umpire's historical NRFI rate minus league avg, regressed toward 0
   - `nrfi_label` (bool), `p_nrfi_model` (float), `p_nrfi_market` (float)
   - `p_nrfi_model` is stored at pipeline run time by `run_daily.py` for result tracking in `post_results.py`

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
- `_pitcher_rolling_features(starts_df, before_date, n=5)` — computes last-n-starts ERA proxy, WHIP proxy, first-inning ERA, avg velocity, velocity trend, and days rest from the per-start DataFrame. Returns dict with keys: `last5_era`, `last5_whip`, `first_inn_era`, `avg_velo`, `velo_trend`, `days_rest`.
- `build_features_for_season(season)` — main entry point, idempotent (skips existing rows).

### `backend/data/fetch_today.py`
- Fetches today's schedule + probable starters from MLB Stats API.
- Filters to game types R/P/F/D/L/W (skips spring training type S).

### `backend/data/fetch_odds.py`
- `_TEAM_NAME_TO_ABBREV` — maps The Odds API full team names → Statcast abbreviations. Includes `"Athletics": "ATH"`.
- `estimate_p_nrfi_from_total(total)` — Poisson approximation: `λ = (total/18) × 0.74`, `P(NRFI) = e^(-2λ)`. Calibrated so total=8.5 → P(NRFI)≈0.50. Used as fallback only.
- `_extract_best_markets()` — uses preferred bookmaker (DraftKings) but falls back to other bookmakers if totals are missing.
- `_fetch_event_ids(date_str)` — fetches MLB event IDs from `/v4/sports/baseball_mlb/events` endpoint for matching games to first-inning odds.
- `_fetch_first_inn_odds(event_id)` — fetches `totals_1st_1_innings` from the event-specific `/events/{id}/odds` endpoint (NOT the general `/odds/` endpoint — that returns 422 for this market). Returns preferred bookmaker's over/under American odds.
- `p_nrfi_market` priority: (1) vig-removed implied probability from actual NRFI Under odds, (2) Poisson approximation from game total as fallback.
- Game matching uses `commenceTimeFrom: {date}T00:00:00Z` to `commenceTimeTo: {date+1}T12:00:00Z` — the upper bound extends to the next day at noon UTC to capture US West Coast games that start after midnight UTC. Do NOT change this back to `{date}T23:59:59Z`.
- **Exact date matching**: tries exact game_date match first, falls back to ±1 day only for edge cases like Tokyo Series. This prevents back-to-back series odds from updating the wrong game's row.
- **Upsert logic**: queries for existing `Odds` row by `(game_id, source)` before inserting to prevent duplicate rows across pipeline re-runs.
- **Total sanity check**: rejects totals outside 5.0–15.0 as likely alternate/half-game market lines leaking in from fallback bookmakers.

### `scripts/run_daily.py`
Daily pipeline (runs at 9:03 AM Pacific via Docker cron scheduler — `TZ: America/Los_Angeles` set in docker-compose.yml):
0. `post_results()` — post yesterday's results to Discord (non-fatal)
1. `fetch_schedule(target)` — MLB Stats API schedule + probable pitchers + HP umpire
2. Insert `Game`, `GamePitchers`, `GameUmpire` rows (idempotent); patches `game_time` on existing rows if NULL
3. `build_features_for_season(season)` — builds NrfiFeatures for new games
4. `fetch_and_store_odds(date_str)` — odds ingestion (non-fatal if fails)
5. Store `p_nrfi_model` in `nrfi_features` for each game (only if currently NULL)
6. `post_predictions(target_date)` — Discord picks post (non-fatal)

### `scripts/start_cron.sh`
- Dumps container env vars to `/etc/environment` so cron jobs can access `DATABASE_URL` etc.
- Installs crontab:
  - `3 9 * * *` → `run_daily.py` (morning pipeline)
  - `0 12 * * *` → `refresh_odds.py` (noon odds refresh)
  - `0 16 * * *` → `refresh_odds.py` (4 PM odds refresh)
  - `0 2 * * *` → `backfill_game_results.py` (nightly results fill)

### `scripts/refresh_odds.py`
- Checks for games with `p_nrfi_market IS NULL` for today's date.
- If any found: re-fetches odds, then posts a Discord update only for games that newly received lines.
- No-op if all games already have odds.

### `scripts/post_discord.py`
- Posts today's picks as Discord embeds — one per game, sorted highest edge first.
- Embed title: `{away} @ {home}  ·  {time ET} / {time CT} / {time PT}` (game time shown in all three US timezones).
- Each embed shows: pitcher matchup, NRFI/YRFI American odds, `Model X% · Mkt Y% · Edge +Z%`, plus a plain-English recommendation.
- Recommendation tiers: 🟢 Bet NRFI (≥+2%), 🟡 Lean NRFI (0–2%), 🟡 Lean YRFI (0 to -2%), 🔴 Fade NRFI (≤-2%).
- Color-coded: green = value play, yellow = lean, red = negative edge, gray = no market data.
- `VALUE_PLAY_THRESHOLD` read from `VALUE_PLAY_THRESHOLD_PP` env var (default: 2 pp).
- Game times sourced from `Game.game_time` (stored by `run_daily.py`), converted from UTC to ET/CT/PT via `zoneinfo`.

### `scripts/post_results.py`
- Posts yesterday's results and season-to-date record to Discord.
- Only tracks games where the model had **positive edge** (edge > 0) as picks.
- Two embeds: yesterday's game-by-game results + season W-L for all plays and value plays.

### `scripts/entrypoint.sh`
- Runs on backend container startup.
- Step 1: `bootstrap_db.py` (idempotent table creation).
- Step 2: If `games` table is empty, launches full backfill pipeline in the background:
  - `backfill_history.py` → `build_features_for_season` → `backfill_game_parks.py` → `backfill_weather.py` → `backfill_park_factors.py` → `backfill_umpire_assignments.py` → `backfill_ump_features.py`
- Step 3: Starts uvicorn immediately (API available before backfill finishes).
- Logs to `/app/logs/backfill.log`.

## Backfill Script Order (Fresh Deploy)

When running backfills manually, order matters due to dependencies:

```
1. backfill_history.py               # games, pitchers, game_pitchers
2. build_features_for_season (all)   # nrfi_features rows
3. backfill_game_parks.py            # Game.park — needed by weather + park factors
4. backfill_weather.py               # temperature/wind columns in nrfi_features
5. backfill_park_factors.py          # park_factor in nrfi_features
6. backfill_umpire_assignments.py    # game_umpires table
7. backfill_ump_features.py          # ump_nrfi_rate_above_avg in nrfi_features
8. backfill_pitcher_rest.py          # home_sp_days_rest / away_sp_days_rest in nrfi_features
```

`entrypoint.sh` runs steps 1–7 automatically on a fresh deploy. Step 8 must currently be run manually after `migrate_add_pitcher_rest.py`.

## Modeling Rules

### Current feature set (30 features in `FEATURE_COLS`)
See `backend/modeling/train_model.py` for the full list. All features including weather, umpire, and pitcher rest are active in `FEATURE_COLS`.

### `train_model.py`
- Trains **both** logistic regression (LR) and XGBoost (XGB), prints side-by-side metrics.
- Saves whichever model wins on **validation AUC**.
- Chronological 80/10/10 train/val/test split (no shuffling).
- LR pipeline: `SimpleImputer(median)` → `StandardScaler` → `LogisticRegression(max_iter=1000)`
- XGB pipeline: `SimpleImputer(median)` → `XGBClassifier` with strong regularisation to prevent overfitting:
  - `max_depth=3`, `min_child_weight=80`, `gamma=1.0`, `reg_alpha=0.5`, `reg_lambda=5.0`
- Evaluates AUC, log loss, Brier score on all three splits.
- Logs LR feature coefficients and XGB feature importances.

### `model_classes.py`
- Defines `XGBModel` and `CalibratedModel` used by the pickle. Must be importable at load time.
- Do NOT move or rename these classes — pickle load will break.

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
- Park factors use only data from seasons prior to the target game's season.

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
