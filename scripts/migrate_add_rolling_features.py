"""
scripts/migrate_add_rolling_features.py

Adds the 10 within-season rolling pitcher feature columns to nrfi_features.
Safe to run multiple times — skips columns that already exist.

Usage:
    DATABASE_URL=postgresql://nrfi:nrfi@localhost:5432/nrfi python scripts/migrate_add_rolling_features.py
"""

import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine

NEW_COLUMNS = [
    ("home_sp_last5_era",     "DOUBLE PRECISION"),
    ("home_sp_last5_whip",    "DOUBLE PRECISION"),
    ("home_sp_first_inn_era", "DOUBLE PRECISION"),
    ("home_sp_avg_velo",      "DOUBLE PRECISION"),
    ("home_sp_velo_trend",    "DOUBLE PRECISION"),
    ("away_sp_last5_era",     "DOUBLE PRECISION"),
    ("away_sp_last5_whip",    "DOUBLE PRECISION"),
    ("away_sp_first_inn_era", "DOUBLE PRECISION"),
    ("away_sp_avg_velo",      "DOUBLE PRECISION"),
    ("away_sp_velo_trend",    "DOUBLE PRECISION"),
]

with engine.begin() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'nrfi_features'"
    ))
    existing = {row[0] for row in result}

    added = []
    for col, col_type in NEW_COLUMNS:
        if col in existing:
            print(f"  SKIP  {col} (already exists)")
        else:
            conn.execute(text(f"ALTER TABLE nrfi_features ADD COLUMN {col} {col_type}"))
            added.append(col)
            print(f"  ADDED {col}")

print(f"\nDone. Added {len(added)} column(s).")
