# NRFI Analytics Backend

A machine learning backend that predicts the probability of **No Run First Inning (NRFI)** outcomes in MLB games, compares those probabilities against market-implied odds, and posts daily picks and results to Discord.

---

## What is NRFI?

A **NRFI** (No Run First Inning) bet wins if neither team scores in the first inning of a game. Historically ~55% of MLB games are NRFI. Books price the bet via game totals — the higher the total, the more run-scoring expected, and the cheaper the NRFI odds.

The edge this system looks for: situations where our model thinks NRFI is more likely than the market implies, based on pitcher quality, team tendencies, park, weather, and umpire.

---

## How It Works

### 1. Data Pipeline (runs daily at 9:03 AM ET)

```
MLB Stats API → today's schedule + probable starters
              → insert Game + GamePitchers rows
              → build NrfiFeatures for new games
The Odds API  → fetch totals → compute p_nrfi_market
Discord       → post picks
```

### 2. Odds Refresh (12:00 PM + 4:00 PM ET)

West Coast games and late slates often don't have lines posted at 9 AM. The refresh runs twice to catch them, posting a Discord update only for games that previously showed N/A.

### 3. Results (2:00 AM ET, next day)

After all West Coast games finish, a backfill script pulls first-inning run data from the MLB Stats API and fills in outcomes. The following morning's pipeline opens by posting yesterday's scorecard to Discord.

---

## The Model

### Training Data
- 2015–present, sourced from Baseball Savant (Statcast) via `pybaseball`
- Chronological 80/10/10 train/val/test split — **no shuffling**, no data leakage
- Both XGBoost and Logistic Regression are trained; whichever wins on validation AUC is saved

### Feature Set (23 features)
| Category | Features |
|---|---|
| Prior-season SP stats (Fangraphs) | ERA, WHIP, K%, BB%, HR/9 for home + away SP |
| Rolling in-season SP form | Last-5 ERA proxy, last-5 WHIP proxy, first-inning ERA, avg fastball velo, velo trend (home + away) |
| Team offense | Home + away first-inning runs per game (rolling, pre-game only) |
| Park | Park factor (computed from historical first-inning run rates at each venue) |
| Weather | Temperature (°F), wind speed, wind blowing out to CF (mph), dome flag |
| Umpire | HP umpire's historical NRFI rate vs league average (regressed) |

### Anti-Leakage Rules
- Prior-season Fangraphs stats use `season - 1` only
- Rolling pitcher stats use only starts **before** the target game date
- Team stats use only games **before** the target game date
- Park factors use only data from prior seasons

> **Note:** Weather and umpire features are collected and stored but are not yet included in `FEATURE_COLS` in `train_model.py`. The model currently trains on 23 features (pitcher + team + park). Adding weather and umpire is the next planned improvement.

### XGBoost Hyperparameters
Tuned conservatively to prevent overfitting on a relatively small dataset (~10 seasons):
- `max_depth=3`, `min_child_weight=80`, `gamma=1.0`, `reg_alpha=0.5`, `reg_lambda=5.0`

---

## Edge Calculation

### Market-Implied P(NRFI)

Derived from the game total using a Poisson approximation:

```
λ = (total / 18) × 0.74      # expected runs per half-inning in the 1st
P(NRFI) = e^(-2λ)             # both teams score 0 in the 1st
```

Calibrated so that a total of **8.5 → P(NRFI) ≈ 50%**. This is not a perfect model of how books actually price NRFI — books use a more complex model — but it's a reasonable approximation for identifying edge.

### Edge

```
edge = p_nrfi_model − p_nrfi_market
```

Positive edge means our model thinks NRFI is **more likely** than the market implies. Negative edge means the market is more confident in NRFI than we are.

### Recommendation Tiers

| Edge | Label | Meaning |
|---|---|---|
| ≥ +2% | 🟢 Bet NRFI | Clear model edge over market |
| 0% to +2% | 🟡 Lean NRFI | Slight edge, not a strong value play |
| -2% to 0% | 🟡 Lean YRFI | Market prices NRFI slightly above model |
| ≤ -2% | 🔴 Fade NRFI | Market significantly overvalues NRFI |

The +2% threshold is configurable via the `VALUE_PLAY_THRESHOLD_PP` environment variable.

---

## Discord Output

### Morning Picks (9:03 AM)
One embed per game, sorted highest edge first:
```
AZ @ LAD
Model 54% · Mkt 48% · Edge +6%
🟢 Bet NRFI — our model gives NRFI a 54% chance vs the market's implied
probability. We see 6% of extra value here.
```

### Odds Update (12:00 PM + 4:00 PM)
Only posts games that had N/A lines in the morning. Same format as above. No-op if all games already had lines.

### Yesterday's Results (next 9:03 AM)
```
Yesterday's Results — 2026-03-26
✅ AZ @ LAD — NRFI ✓  |  Model 54% · Mkt 48% · Edge +6%
❌ CLE @ SEA — YRFI  |  Model 54% · Mkt 59% · Edge -4%
Yesterday: 1-1 (50.0%)

Season Record
All Plays (model > market): 1-1 (50.0%)    Value Plays (edge > +2%): 1-0 (100.0%)
```

Only games where the model had **positive edge** appear in results. Negative-edge games are not tracked as picks.

---

## Setup & Deployment

### Prerequisites
- Docker + Docker Compose
- The Odds API key (free tier works)
- Discord webhook URL

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Postgres connection string (set automatically in docker-compose) |
| `ODDS_API_KEY` | Yes | The Odds API v4 key |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook — if unset, all Discord steps are silently skipped |
| `MODEL_ARTIFACT_PATH` | No | Path to model pickle (default: `models/nrfi_model.pkl`) |
| `VALUE_PLAY_THRESHOLD_PP` | No | Edge threshold in percentage points for "value play" label (default: `2`) |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |

### First Deploy

```bash
cp .env.example .env          # fill in ODDS_API_KEY and DISCORD_WEBHOOK_URL
docker compose up -d
```

On first start, the backend container will:
1. Create all DB tables
2. Detect an empty database
3. Launch the full historical backfill pipeline in the background:
   - Games + pitchers (2015–present) via Statcast — **takes several hours**
   - NrfiFeatures for all historical games
   - Park names, weather, park factors, umpire assignments, umpire features
4. Start the API immediately (returns empty results until backfill fills in data)

Monitor backfill progress:
```bash
docker exec -it nrfi-backend-1 tail -f /app/logs/backfill.log
```

### Subsequent Restarts

The entrypoint detects existing data and skips the backfill entirely. Cold start is ~5 seconds.

### Training the Model

The model is **not** trained automatically. After the backfill completes, train it manually:

```bash
docker exec -it nrfi-backend-1 python backend/modeling/train_model.py
```

This saves the winning model to `models/nrfi_model.pkl` (on the `model_store` Docker volume, shared between `backend` and `scheduler`). Re-train whenever you want to incorporate new season data.

---

## Manual Operations

### Re-post today's picks
```bash
docker exec -it nrfi-backend-1 python scripts/post_discord.py
```

### Manually refresh odds (e.g. lines weren't up at 9 AM)
```bash
docker exec -it nrfi-backend-1 python scripts/refresh_odds.py
```

### Score a specific past date
```bash
docker exec -it nrfi-backend-1 python scripts/post_results.py --date 2026-04-05
```

### Fill in game outcomes for a past date
```bash
docker exec -it nrfi-backend-1 python scripts/backfill_game_results.py --date 2026-04-05
```

### Run the daily pipeline for a specific date
```bash
docker exec -it nrfi-backend-1 python scripts/run_daily.py --date 2026-04-05
```

---

## Cron Schedule

All times Eastern. Configured in `scripts/start_cron.sh`.

| Time | Script | Purpose |
|---|---|---|
| 9:03 AM | `run_daily.py` | Fetch schedule, build features, post picks |
| 12:00 PM | `refresh_odds.py` | Post odds update for any N/A games |
| 4:00 PM | `refresh_odds.py` | Second odds check before first pitch |
| 2:00 AM | `backfill_game_results.py` | Fill in first-inning outcomes after games finish |

---

## Known Gaps & Future Work

### Model
- **Weather and umpire features are not yet in `FEATURE_COLS`** — the columns exist and are populated, but `train_model.py` doesn't include them yet. Adding them is the next planned step.
- **No automated retraining** — model is trained manually. Should be re-trained at the start of each season and periodically mid-season.
- **No YRFI model** — we identify YRFI edges by fading NRFI (negative edge), but there is no dedicated YRFI probability model.
- **park_factor** uses a simple regression toward 1.0 based on sample size. A proper park factor would account for handedness splits and temperature interactions.

### Odds
- **No historical odds** — `p_nrfi_market` is only available for current-season games (The Odds API doesn't provide historical data). Historical features rows have `p_nrfi_market = NULL`.
- **Market approximation is imperfect** — the Poisson model for converting totals → P(NRFI) is a calibrated approximation, not how books actually price the bet. Books use independent home/away scoring models.

### Infrastructure
- **CORS allows all origins** (`*`) — should be tightened once the frontend domain is known.
- **No automated model deployment** — after retraining, the new model file needs to be in place before the next pipeline run.
- **Season record starts from first Discord post** — there is no historical betting record backfill.

---

## Repository Structure

```
backend/
  api/
    main.py               FastAPI app (CORS, router registration)
    routers/
      health.py           GET /health
      games.py            GET /games/today, /games/{id}
      nrfi.py             GET /nrfi/today, /nrfi/{id}
  core/
    config.py             Settings (env vars via pydantic-settings)
  data/
    fetch_stats.py        Statcast + Fangraphs ingestion
    fetch_today.py        MLB Stats API daily schedule
    fetch_odds.py         The Odds API ingestion + p_nrfi_market computation
    build_features.py     NrfiFeatures builder
  db/
    models.py             SQLAlchemy ORM (7 tables)
    session.py            DB engine + SessionLocal
  modeling/
    train_model.py        XGBoost + LR training
    predict.py            Inference (module-level model cache)
    evaluate_model.py     Backtesting + calibration evaluation
    model_classes.py      XGBModel + CalibratedModel (needed for pickle load)
    model_store.py        save/load pickle

scripts/
  entrypoint.sh           Backend startup: bootstrap + conditional backfill + uvicorn
  start_cron.sh           Scheduler startup: env dump + crontab install + cron
  run_daily.py            Daily pipeline (schedule → features → odds → Discord)
  post_discord.py         Post today's picks to Discord
  post_results.py         Post yesterday's results + season record to Discord
  refresh_odds.py         Re-fetch odds for N/A games, post Discord update
  bootstrap_db.py         Create tables (idempotent)
  backfill_history.py     Games + pitchers, 2015–present
  backfill_game_results.py  First-inning outcomes for completed games
  backfill_game_parks.py  Venue names for historical games
  backfill_weather.py     Weather features for historical nrfi_features rows
  backfill_park_factors.py  Real park factors (replaces 1.0 placeholder)
  backfill_umpire_assignments.py  HP umpire per game from MLB Stats API
  backfill_ump_features.py  ump_nrfi_rate_above_avg in nrfi_features

models/
  nrfi_model.pkl          Trained model (on Docker volume, not in git)
```
