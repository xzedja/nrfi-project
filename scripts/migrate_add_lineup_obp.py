"""
scripts/migrate_add_lineup_obp.py

Adds home_lineup_obp and away_lineup_obp columns to nrfi_features.

These store the average prior-season OBP of each team's starting batting lineup
for a given game, fetched from the MLB Stats API boxscore.
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

    if "home_lineup_obp" not in existing:
        conn.execute(text("ALTER TABLE nrfi_features ADD COLUMN home_lineup_obp DOUBLE PRECISION"))
        print("Added home_lineup_obp")
    else:
        print("home_lineup_obp already exists")

    if "away_lineup_obp" not in existing:
        conn.execute(text("ALTER TABLE nrfi_features ADD COLUMN away_lineup_obp DOUBLE PRECISION"))
        print("Added away_lineup_obp")
    else:
        print("away_lineup_obp already exists")

print("Migration complete.")
