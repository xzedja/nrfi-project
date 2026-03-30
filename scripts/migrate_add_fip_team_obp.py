"""
scripts/migrate_add_fip_team_obp.py

Adds pitcher FIP and team OBP/SLG columns to nrfi_features.
"""
import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine

NEW_COLS = [
    ("home_sp_fip",   "DOUBLE PRECISION"),
    ("away_sp_fip",   "DOUBLE PRECISION"),
    ("home_team_obp", "DOUBLE PRECISION"),
    ("away_team_obp", "DOUBLE PRECISION"),
    ("home_team_slg", "DOUBLE PRECISION"),
    ("away_team_slg", "DOUBLE PRECISION"),
]

with engine.begin() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'nrfi_features'"
    ))
    existing = {row[0] for row in result}

    for col, col_type in NEW_COLS:
        if col not in existing:
            conn.execute(text(f"ALTER TABLE nrfi_features ADD COLUMN {col} {col_type}"))
            print(f"Added column: {col}")
        else:
            print(f"Already exists: {col}")

print("Migration complete.")
