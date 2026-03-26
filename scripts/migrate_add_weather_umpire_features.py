"""
scripts/migrate_add_weather_umpire_features.py

Adds weather and umpire columns to nrfi_features and creates the game_umpires table.
Safe to re-run — skips anything that already exists.

New nrfi_features columns:
    temperature_f           DOUBLE PRECISION
    wind_speed_mph          DOUBLE PRECISION
    wind_out_mph            DOUBLE PRECISION  (positive = blowing toward CF)
    is_dome                 DOUBLE PRECISION  (1.0 = dome/closed roof)
    ump_nrfi_rate_above_avg DOUBLE PRECISION

New table:
    game_umpires (id, game_id FK, ump_id, ump_name)

Usage:
    DATABASE_URL=postgresql://... python scripts/migrate_add_weather_umpire_features.py
"""

import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine

NEW_NRFI_COLUMNS = [
    ("temperature_f",           "DOUBLE PRECISION"),
    ("wind_speed_mph",          "DOUBLE PRECISION"),
    ("wind_out_mph",            "DOUBLE PRECISION"),
    ("is_dome",                 "DOUBLE PRECISION"),
    ("ump_nrfi_rate_above_avg", "DOUBLE PRECISION"),
]

with engine.begin() as conn:
    # ------------------------------------------------------------------ #
    # 1. Add new columns to nrfi_features
    # ------------------------------------------------------------------ #
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'nrfi_features'"
    ))
    existing_cols = {row[0] for row in result}

    added_cols = []
    for col, col_type in NEW_NRFI_COLUMNS:
        if col in existing_cols:
            print(f"  SKIP  nrfi_features.{col} (already exists)")
        else:
            conn.execute(text(f"ALTER TABLE nrfi_features ADD COLUMN {col} {col_type}"))
            added_cols.append(col)
            print(f"  ADDED nrfi_features.{col}")

    # ------------------------------------------------------------------ #
    # 2. Create game_umpires table if it doesn't exist
    # ------------------------------------------------------------------ #
    result = conn.execute(text(
        "SELECT to_regclass('public.game_umpires')"
    ))
    table_exists = result.scalar() is not None

    if table_exists:
        print("  SKIP  game_umpires table (already exists)")
    else:
        conn.execute(text("""
            CREATE TABLE game_umpires (
                id      SERIAL PRIMARY KEY,
                game_id INTEGER NOT NULL UNIQUE REFERENCES games(id),
                ump_id  INTEGER NOT NULL,
                ump_name VARCHAR(100)
            )
        """))
        conn.execute(text("CREATE INDEX ix_game_umpires_game_id ON game_umpires(game_id)"))
        conn.execute(text("CREATE INDEX ix_game_umpires_ump_id  ON game_umpires(ump_id)"))
        print("  CREATED game_umpires table + indexes")

print(f"\nDone. Added {len(added_cols)} column(s) to nrfi_features.")
