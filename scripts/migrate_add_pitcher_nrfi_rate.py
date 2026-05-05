"""
scripts/migrate_add_pitcher_nrfi_rate.py

Adds home_sp_nrfi_rate_season and away_sp_nrfi_rate_season columns to nrfi_features.
These store the pitcher's in-season NRFI hold rate (fraction of starts before this game
where they held the opponent scoreless in their half of the 1st inning). NULL if < 3 starts.

Run once:
    docker exec -it nrfi-backend-1 python scripts/migrate_add_pitcher_nrfi_rate.py
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
    if "home_sp_nrfi_rate_season" not in existing:
        conn.execute(text(
            "ALTER TABLE nrfi_features ADD COLUMN home_sp_nrfi_rate_season DOUBLE PRECISION"
        ))
        added.append("home_sp_nrfi_rate_season")

    if "away_sp_nrfi_rate_season" not in existing:
        conn.execute(text(
            "ALTER TABLE nrfi_features ADD COLUMN away_sp_nrfi_rate_season DOUBLE PRECISION"
        ))
        added.append("away_sp_nrfi_rate_season")

if added:
    print(f"Added columns: {', '.join(added)}")
else:
    print("Columns already exist — nothing to do.")
