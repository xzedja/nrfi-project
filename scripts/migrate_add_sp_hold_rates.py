"""
scripts/migrate_add_sp_hold_rates.py

Adds home_sp_hold_rate and away_sp_hold_rate columns to the nrfi_features table.

Run once:
    DATABASE_URL=postgresql://... python scripts/migrate_add_sp_hold_rates.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import text

from backend.db.session import engine


def migrate() -> None:
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'nrfi_features'"
        ))
        existing = {row[0] for row in result}

        added = []
        if "home_sp_hold_rate" not in existing:
            conn.execute(text(
                "ALTER TABLE nrfi_features ADD COLUMN home_sp_hold_rate DOUBLE PRECISION"
            ))
            added.append("home_sp_hold_rate")

        if "away_sp_hold_rate" not in existing:
            conn.execute(text(
                "ALTER TABLE nrfi_features ADD COLUMN away_sp_hold_rate DOUBLE PRECISION"
            ))
            added.append("away_sp_hold_rate")

        if added:
            print(f"Added columns: {', '.join(added)}")
        else:
            print("Columns already exist — nothing to do.")


if __name__ == "__main__":
    migrate()
