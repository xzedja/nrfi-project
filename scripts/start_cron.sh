#!/usr/bin/env bash
# scripts/start_cron.sh
#
# Entrypoint for the scheduler container.
# Writes Docker environment variables into /etc/environment so cron jobs
# can access them (cron doesn't inherit the container's env by default),
# installs the crontab, then starts cron in the foreground.

set -euo pipefail

# Dump current env vars to /etc/environment for cron to source
printenv | grep -v "^_=" > /etc/environment

# Write the crontab
# 9:03 AM  — morning pipeline (schedule + features + odds + Discord post)
# 12:00 PM — odds refresh (posts update for any games that had N/A edges at 9 AM)
# 4:00 PM  — odds refresh (catches any remaining N/A games before first pitch)
# 2:00 AM  — post-game results (fill in first-inning outcomes for completed games)
(
  echo "3 9 * * * . /etc/environment; cd /app && python scripts/run_daily.py >> /app/logs/daily.log 2>&1"
  echo "0 12 * * * . /etc/environment; cd /app && python scripts/refresh_odds.py >> /app/logs/odds_refresh.log 2>&1"
  echo "0 16 * * * . /etc/environment; cd /app && python scripts/refresh_odds.py >> /app/logs/odds_refresh.log 2>&1"
  echo "0 2 * * * . /etc/environment; cd /app && python scripts/backfill_game_results.py >> /app/logs/results.log 2>&1"
) | crontab -

echo "Crontab installed:"
crontab -l

mkdir -p /app/logs

echo "Starting cron..."
# -f keeps cron in the foreground so Docker sees it as the main process
cron -f
