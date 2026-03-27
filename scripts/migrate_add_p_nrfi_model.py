"""
scripts/migrate_add_p_nrfi_model.py

Adds p_nrfi_model column to nrfi_features table.

Usage:
    python scripts/migrate_add_p_nrfi_model.py
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
    if "p_nrfi_model" not in existing:
        conn.execute(text("ALTER TABLE nrfi_features ADD COLUMN p_nrfi_model DOUBLE PRECISION"))
        print("Added p_nrfi_model column.")
    else:
        print("p_nrfi_model column already exists — nothing to do.")
