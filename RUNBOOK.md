# NRFI Project Runbook

## Setup (do this once per terminal session)

```bash
cd ~/Projects/nrfi-project
source .venv/bin/activate
```

You'll see `(.venv)` at the start of your prompt. All commands below require the venv to be active.

---

## Retrain the model

```bash
python -m backend.modeling.train_model
```

Trains logistic regression and XGBoost side-by-side, prints metrics for both,
then saves the better model (by validation AUC) to `models/nrfi_model.pkl`.

---

## Evaluate the saved model

```bash
python -m backend.modeling.evaluate_model
```

Reports overall AUC, per-season breakdown, calibration table, and edge analysis
on all historical labeled data.

To evaluate a single season only:

```bash
python -m backend.modeling.evaluate_model --season 2023
```

---

## Start the API server (local dev)

```bash
uvicorn backend.api.main:app --reload
```

Open `http://localhost:8000/docs` in your browser to see and test all endpoints
interactively. `--reload` restarts the server automatically when you edit code.

Key endpoints:
- `GET /health` — confirms DB is reachable
- `GET /nrfi/today` — predictions for all of today's games
- `GET /nrfi/{game_id}` — prediction for one game by internal DB id
- `GET /games/today` — today's games from the DB

---

## Run the daily pipeline manually

```bash
python scripts/run_daily.py
```

Fetches today's schedule + probable starters, builds features, and pulls odds.
Run each morning before games start. To target a specific date:

```bash
python scripts/run_daily.py --date 2026-03-15
```

---

## Start everything with Docker

```bash
docker-compose up --build
```

Starts three services:
- **db** — Postgres on port 5432
- **backend** — API server on port 8000
- **scheduler** — runs the daily pipeline automatically at 9:03 AM

First run takes a few minutes to build. Subsequent starts are faster:

```bash
docker-compose up
```

To stop everything:

```bash
docker-compose down
```

---

## One-time setup (starting from scratch)

Only needed if the database is empty or you're setting up on a new machine.

```bash
python scripts/bootstrap_db.py          # creates all tables
python scripts/backfill_history.py      # loads 2015–present (takes several hours)
python -m backend.modeling.train_model  # trains and saves the model
```

---

## Environment variables

The project reads secrets from a `.env` file in the project root. Required variables:

```
DATABASE_URL=postgresql://nrfi:nrfi@localhost:5432/nrfi
ODDS_API_KEY=your_key_here
```

The `.env` file is gitignored — never commit it.
