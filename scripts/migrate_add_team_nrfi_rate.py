"""
scripts/migrate_add_team_nrfi_rate.py

Adds home_team_nrfi_rate_l30 and away_team_nrfi_rate_l30 columns to nrfi_features.
These store the rolling 30-game NRFI rate (cross-season) for each team,
used as a model feature in place of the market-known park/weather/ump features.

Run once:
    docker exec -it nrfi-project-backend-1 python scripts/migrate_add_team_nrfi_rate.py
"""

import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine

with engine.begin() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'nrfi_features'"
    ))
    existing = {row[0] for row in result}

    added = []
    if "home_team_nrfi_rate_l30" not in existing:
        conn.execute(text(
            "ALTER TABLE nrfi_features ADD COLUMN home_team_nrfi_rate_l30 DOUBLE PRECISION"
        ))
        added.append("home_team_nrfi_rate_l30")

    if "away_team_nrfi_rate_l30" not in existing:
        conn.execute(text(
            "ALTER TABLE nrfi_features ADD COLUMN away_team_nrfi_rate_l30 DOUBLE PRECISION"
        ))
        added.append("away_team_nrfi_rate_l30")

if added:
    print(f"Added columns: {', '.join(added)}")
else:
    print("Columns already exist — nothing to do.")
