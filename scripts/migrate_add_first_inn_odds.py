"""
scripts/migrate_add_first_inn_odds.py

Adds first_inn_over_odds and first_inn_under_odds columns to the odds table.

Usage:
    python scripts/migrate_add_first_inn_odds.py
"""

import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine

with engine.begin() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'odds'"
    ))
    existing = {row[0] for row in result}

    added = []
    if "first_inn_over_odds" not in existing:
        conn.execute(text("ALTER TABLE odds ADD COLUMN first_inn_over_odds INTEGER"))
        added.append("first_inn_over_odds")
    if "first_inn_under_odds" not in existing:
        conn.execute(text("ALTER TABLE odds ADD COLUMN first_inn_under_odds INTEGER"))
        added.append("first_inn_under_odds")

    if added:
        print(f"Added columns: {', '.join(added)}")
    else:
        print("Columns already exist — nothing to do.")
