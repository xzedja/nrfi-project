#!/usr/bin/env bash
# scripts/cron_daily.sh
#
# Wrapper for the daily NRFI pipeline, called by cron.
# Loads environment variables from .env and runs run_daily.py.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/daily.log"
ENV_FILE="$PROJECT_DIR/.env"
PYTHON="$PROJECT_DIR/.venv/bin/python"

# Rotate log if it exceeds 10 MB
if [ -f "$LOG_FILE" ] && [ "$(stat -c%s "$LOG_FILE")" -gt 10485760 ]; then
    mv "$LOG_FILE" "${LOG_FILE}.1"
fi

{
    echo "========================================="
    echo "Daily pipeline started: $(date)"
    echo "========================================="

    # Load .env into the environment
    if [ -f "$ENV_FILE" ]; then
        set -a
        # shellcheck source=/dev/null
        source "$ENV_FILE"
        set +a
    else
        echo "WARNING: .env file not found at $ENV_FILE"
    fi

    cd "$PROJECT_DIR"
    "$PYTHON" scripts/run_daily.py

    echo "Finished: $(date)"
} >> "$LOG_FILE" 2>&1
