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

# Write the crontab — runs daily at 9:03 AM
echo "3 9 * * * . /etc/environment; cd /app && python scripts/run_daily.py >> /app/logs/daily.log 2>&1" | crontab -

echo "Crontab installed:"
crontab -l

mkdir -p /app/logs

echo "Starting cron..."
# -f keeps cron in the foreground so Docker sees it as the main process
cron -f
