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
- **Date cap for current season**: `_season_date_range` caps the end date at `date.today() - timedelta(days=1)` when `season == date.today().year`. This prevents fetching empty future chunks on daily pipeline runs (avoids ~6 wasted API calls per run mid-season).
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

### `backend/data/fetch_lineups.py`
- Fetches actual batting orders from MLB Stats API boxscore endpoint after lineups are posted (typically 3–4 hours before game time).
- `update_lineup_obp_for_date(target_date)` — loads prior-season Fangraphs batting OBP, maps MLB IDs to Fangraphs IDs, computes average OBP for the starting 9, writes `home_lineup_obp` / `away_lineup_obp` to `nrfi_features`.
- Called by `scripts/refresh_lineups.py` hourly from 10 AM–7 PM.
- Lineup OBP features are NULL at the 8:30 AM pipeline run — model falls back to median via `SeasonStartImputer` until lineups post.

### `scripts/refresh_lineups.py`
- Hourly lineup refresh (10 AM–7 PM via cron in `start_cron.sh`).
- Checks for games with `home_lineup_obp IS NULL` for today, calls `update_lineup_obp_for_date`, no-op if all games already have data.
- `home_lineup_obp`, `away_lineup_obp`, and derived `lineup_obp_diff` (away minus home) are all active features in `FEATURE_COLS`.

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
  - `0 8 * * 0` → `train_model.py` (weekly retrain, Sundays at 8:00 AM — before daily pipeline)
  - `30 8 * * *` → `run_daily.py` (morning pipeline at 8:30 AM)
  - `0 10-19 * * *` → `refresh_lineups.py` (hourly lineup refresh, 10 AM–7 PM)
  - `0 12 * * *` → `refresh_odds.py` (noon odds refresh)
  - `0 16 * * *` → `refresh_odds.py` (4 PM odds refresh)
  - `0 2 * * *` → `backfill_game_results.py` (nightly results fill)

### `scripts/refresh_odds.py`
- Checks for games with `p_nrfi_market IS NULL` for today's date.
- If any found: re-fetches odds, then posts a Discord update only for games that newly received lines.
- No-op if all games already have odds.

### `scripts/post_discord.py`
- Posts today's picks as Discord embeds — one per game.
- **Sort order**: by signal tier first (🟢→🟡 NRFI→🔵 YRFI→🟡 YRFI→🔴→⚪ no edge), then by game time (ascending) within each tier.
- Embed title: `{away} @ {home}  ·  {time ET} / {time CT} / {time PT}` (game time shown in all three US timezones).
- Each embed shows: pitcher matchup, NRFI/YRFI American odds, `Model X% · Mkt Y% · Edge +Z%`, plus a plain-English recommendation.
- **Two distinct signals — messaging is intentionally different:**
  - 🟢/🟡 **Model leans** (experimental): labeled as leans, not bets. Historical ROI not confirmed.
  - 🔵 **YRFI signal** (market-driven): confident framing with ROI data. Fires when `p_nrfi_market >= 0.60` regardless of model edge.
- `_HIGH_DISAGREEMENT_THRESHOLD = 0.07` — edges ≥7% trigger a diagnostic note ("likely model data issue, not a bet").
- Color-coded: green = model leans NRFI (≥+2%), yellow = slight lean, **blue = YRFI signal**, red = model leans YRFI, gray = no market data / anchored.
- `VALUE_PLAY_THRESHOLD` read from `VALUE_PLAY_THRESHOLD_PP` env var (default: 2 pp).
- `_EDGE_ZERO_THRESHOLD = 0.001` — edges smaller than 0.1% shown as gray (early-season anchor, all features at median).
- Early-season header notice (before April 15) explicitly states YRFI signals remain active regardless of model confidence.
- Game times sourced from `Game.game_time` (stored by `run_daily.py`), converted from UTC to ET/CT/PT via `zoneinfo`.

### `scripts/post_results.py`
- Posts yesterday's results and season-to-date record to Discord.
- Tracks two separate signals:
  - **Model picks**: games where edge > 0. Embeds: yesterday's results + season W-L (all plays + value plays).
  - **YRFI signal**: games where `p_nrfi_market >= 0.60` regardless of model edge. Bet YRFI on these. Historically +46–54% ROI.
- Three embeds total: yesterday's NRFI results, season model record, season YRFI signal record.
- `YRFI_SIGNAL_THRESHOLD` env var controls the 60% cutoff (default 0.60).

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

### Current feature set (~22 active features in `FEATURE_COLS`)
See `backend/modeling/train_model.py` for the full list. Weather, umpire, park factor, and `p_nrfi_market` have been **removed** from `FEATURE_COLS` — model trains only on pre-game, non-market-known features. Edge is computed at prediction time only (`p_nrfi_model - p_nrfi_market`). The file defines 44 total features but 22 show 0.000 importance (see Known Gaps in CLAUDE.md).

### `train_model.py`
- Trains **both** logistic regression (LR) and XGBoost (XGB), prints side-by-side metrics.
- Saves whichever model wins on **validation AUC**, Platt-calibrated on the calib set.
- **Dynamic expanding window split** (no hardcoded years):
  - `_DATA_START_YEAR = 2015` — earliest season included in training data (expanded from 2023; 25,564 game rows)
  - `_CALIB_WINDOW_DAYS = 365` — Platt calibration set spans the last full year (always reaches into prior season regardless of calendar position; 365 days avoids the offseason gap problem of smaller windows)
  - `_VAL_WINDOW_DAYS = 7` — model selection set is the last 7 days of completed games
  - **Fit set**: all games from `_DATA_START_YEAR` through `calib_cutoff`
  - **Calib set**: `calib_cutoff` to `val_cutoff` (~2,400+ games in season, ~365 days)
  - **Val set**: last 7 days of completed games (model selection)
  - **Test set**: today's games (empty for in-season picks; guarded against empty-set crash)
  - The fit set automatically grows each week as games age past the 7-day val window
- LR pipeline: `SeasonStartImputer` → `StandardScaler` → `LogisticRegression(max_iter=1000)`
- XGB pipeline: `SeasonStartImputer` → `XGBClassifier` with strong regularisation:
  - `max_depth=3`, `min_child_weight=60`, `gamma=0.5`, `reg_alpha=0.3`, `reg_lambda=2.0`
- Winner is Platt-calibrated using a logistic regression fit on calib set raw scores → saved as `CalibratedModel`.
- Evaluates AUC, log loss, Brier score on all splits; empty splits (e.g. empty test set) are skipped safely.
- Saves training metadata to `models/nrfi_model.meta.json`: training date ranges, game counts, AUC, Brier per split.
- **Current trained model: XGBoost** (val AUC 0.5698 vs LR 0.5593). With 2015+ data XGB now generalises well; LR was preferred on the smaller 2023+ dataset.
- Retrain manually: `docker exec -it nrfi-backend-1 python -m backend.modeling.train_model` (container name is `nrfi-backend-1`, NOT `nrfi-project-backend-1`).
- Retrain automatically: every Sunday at 8:00 AM via cron (before daily pipeline at 8:30 AM).
- **Delta model (XGBRegressor on residual y' = nrfi_label - p_nrfi_market) was tried and reverted.** It produced uniform YRFI bias at season start because without Statcast data all features impute to median, outputting a constant ~-10% delta for every game. Do not reintroduce until rolling pitcher features are populated (typically 5–6 weeks into season).
- **Platt calibration pitfall**: do NOT shrink `_CALIB_WINDOW_DAYS` below ~180. Smaller windows during the offseason span Dec–Feb (near-zero MLB games), giving the Platt scaler only 30–70 games to fit on — output collapses to a single probability with no spread.

### `model_classes.py`
- Defines `SeasonStartImputer`, `XGBModel`, and `CalibratedModel` used by the pickle. Must be importable at load time.
- `SeasonStartImputer` — two-pass imputer: proxy-fills NULL rolling stats with prior-season equivalents (e.g. `last5_era → era`), then median-fills anything remaining.
- Do NOT move or rename these classes — pickle load will break.

### `model_store.py`
- `save_model(model, path)` and `load_model(path)` via pickle.
- Default path: `models/nrfi_model.pkl`

### `predict.py`
- Module-level `_model` / `_model_mtime` cache — auto-reloads when the pkl file changes on disk. No container restart needed after retraining; the next prediction call picks up the new model automatically.
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

## YRFI Heavy-Favorite Signal

A structural market inefficiency discovered via backtest (2023–2025, 2,700+ bets):
- When the market implies **≥60% probability of NRFI**, the actual NRFI rate is only ~48–54%
- Betting YRFI on these games produces **+46–54% ROI** historically (2023: +54.65%, 2024: +46.34%)
- The signal is market-driven and requires no model — just `p_nrfi_market >= 0.60`
- 2025 sample is only 39 bets (system went live mid-season) — insufficient to confirm trend
- Tracked in `post_results.py` (third embed) and shown as 🔵 blue in Discord picks/bot
- `_YRFI_SIGNAL_THRESHOLD = 0.60` in both `post_discord.py` and `discord_bot.py`

## Historical Odds Backfill

`scripts/backfill_historical_odds.py` — hybrid backfill of `p_nrfi_market` for historical games.

**Two paths:**
- **Actual path** (recent dates): fetches real NRFI/YRFI lines from The Odds API historical endpoint, blends 80% actual + 20% Poisson. Costs ~151 API credits per game day.
- **Poisson path** (older dates): derives `p_nrfi_market` from game total via Poisson approximation. Costs ~1 credit per day.

**Coverage notes (as of April 2026):**
- 2023–2024: good coverage of actual first-inning odds
- 2025: patchy — only April and July have actual first-inning odds in The Odds API historical archive. May, June, August, September return empty.
- Backfill was stopped mid-July 2025 to preserve API credits (~8,400 remaining needed for live pipeline ~450 credits/day)

**Re-run when API credits reset:**
```bash
# Dry run first to estimate credit cost
docker exec -it nrfi-project-backend-1 python scripts/backfill_historical_odds.py \
  --start 2025-03-27 --end 2025-09-28 --recent-days 365 --dry-run

# Full run (omit --dry-run)
docker exec -it nrfi-project-backend-1 python scripts/backfill_historical_odds.py \
  --start 2025-03-27 --end 2025-09-28 --recent-days 365
```

The script is idempotent — skips rows that already have `p_nrfi_market` unless `--overwrite` is passed.

After backfill, re-run the backtest to see updated 2025 YRFI signal sample:
```bash
docker exec -it nrfi-project-backend-1 python scripts/backtest.py --real-odds-only --start 2023 --end 2025
```

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
