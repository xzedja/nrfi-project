"""
scripts/migrate_add_first_inn_features.py

Adds first-inning Statcast feature columns to nrfi_features:
    home_sp_first_inn_k_pct
    home_sp_first_inn_bb_pct
    home_sp_first_inn_hard_pct
    away_sp_first_inn_k_pct
    away_sp_first_inn_bb_pct
    away_sp_first_inn_hard_pct

Run once before backfilling or retraining.

Usage:
    python scripts/migrate_add_first_inn_features.py
"""

import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine

NEW_COLS = [
    "home_sp_first_inn_k_pct",
    "home_sp_first_inn_bb_pct",
    "home_sp_first_inn_hard_pct",
    "away_sp_first_inn_k_pct",
    "away_sp_first_inn_bb_pct",
    "away_sp_first_inn_hard_pct",
]

with engine.begin() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'nrfi_features'"
    ))
    existing = {row[0] for row in result}

    for col in NEW_COLS:
        if col not in existing:
            conn.execute(text(f"ALTER TABLE nrfi_features ADD COLUMN {col} DOUBLE PRECISION"))
            print(f"Added column: {col}")
        else:
            print(f"Already exists: {col}")

print("Migration complete.")
