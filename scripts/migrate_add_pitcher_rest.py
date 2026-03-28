"""
scripts/migrate_add_pitcher_rest.py

Adds home_sp_days_rest and away_sp_days_rest columns to the nrfi_features table.

Usage:
    python scripts/migrate_add_pitcher_rest.py
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
    if "home_sp_days_rest" not in existing:
        conn.execute(text("ALTER TABLE nrfi_features ADD COLUMN home_sp_days_rest DOUBLE PRECISION"))
        added.append("home_sp_days_rest")
    if "away_sp_days_rest" not in existing:
        conn.execute(text("ALTER TABLE nrfi_features ADD COLUMN away_sp_days_rest DOUBLE PRECISION"))
        added.append("away_sp_days_rest")

    if added:
        print(f"Added columns: {', '.join(added)}")
    else:
        print("Columns already exist — nothing to do.")
