"""
scripts/migrate_add_game_time.py

Adds game_time column to the games table.

Usage:
    python scripts/migrate_add_game_time.py
"""

import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine

with engine.begin() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'games'"
    ))
    existing = {row[0] for row in result}

    if "game_time" not in existing:
        conn.execute(text("ALTER TABLE games ADD COLUMN game_time VARCHAR(30)"))
        print("Added column: game_time")
    else:
        print("Column already exists — nothing to do.")
