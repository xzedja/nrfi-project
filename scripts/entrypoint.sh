#!/usr/bin/env bash
# scripts/entrypoint.sh
#
# Backend container startup sequence:
#   1. Create DB tables (idempotent)
#   2. If DB is empty, run the full historical backfill pipeline in the background
#   3. Start the API server immediately (don't wait for backfill)
#
# Backfill order matters:
#   backfill_history        → games, pitchers, game_pitchers
#   build_features          → nrfi_features rows (needs games + pitchers)
#   backfill_game_parks     → Game.park (needed by weather + park factors)
#   backfill_weather        → weather columns in nrfi_features
#   backfill_park_factors   → park_factor in nrfi_features
#   backfill_umpire_assignments → game_umpires table
#   backfill_ump_features   → ump_nrfi_rate_above_avg in nrfi_features
#
# Monitor progress: tail -f /app/logs/backfill.log

set -euo pipefail

mkdir -p /app/logs

echo "=== NRFI Backend Startup ==="

# Step 1: Bootstrap DB schema
echo "Bootstrapping DB schema..."
python scripts/bootstrap_db.py

# Step 2: Check if historical data already exists
GAME_COUNT=$(python - <<'EOF'
import sys
sys.path.insert(0, ".")
from backend.db.session import SessionLocal
from backend.db.models import Game
db = SessionLocal()
count = db.query(Game).count()
db.close()
print(count)
EOF
)

if [ "$GAME_COUNT" -eq 0 ]; then
    echo "No historical data found — starting full backfill pipeline in background..."
    (
        set -e
        LOG=/app/logs/backfill.log

        run() {
            echo "" >> "$LOG"
            echo "=== $(date '+%Y-%m-%d %H:%M:%S') — $1 ===" >> "$LOG"
            python "$1" >> "$LOG" 2>&1
        }

        run scripts/backfill_history.py

        python - >> "$LOG" 2>&1 <<'PYEOF'
import sys; sys.path.insert(0, ".")
from datetime import date
from backend.data.build_features import build_features_for_season
for season in range(2015, date.today().year + 1):
    print(f"Building features for {season}...")
    build_features_for_season(season)
PYEOF

        run scripts/backfill_game_parks.py
        run scripts/backfill_weather.py
        run scripts/backfill_park_factors.py
        run scripts/backfill_umpire_assignments.py
        run scripts/backfill_ump_features.py

        echo "" >> "$LOG"
        echo "=== $(date '+%Y-%m-%d %H:%M:%S') — Full backfill complete ===" >> "$LOG"
    ) >> /app/logs/backfill.log 2>&1 &

    echo "Backfill started (PID $!). Monitor with: tail -f /app/logs/backfill.log"
else
    echo "Historical data present ($GAME_COUNT games) — skipping backfill."
fi

# Step 3: Start the API
echo "Starting API server..."
exec uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
