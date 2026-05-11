"""
scripts/migrate_add_variant_predictions.py

Adds p_nrfi_var_a and p_nrfi_var_b columns to nrfi_features for tracking
variant model predictions alongside the baseline.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import text
from backend.db.session import engine


def main() -> None:
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'nrfi_features'"
        ))
        existing = {row[0] for row in result}

        added = []
        for col in ("p_nrfi_var_a", "p_nrfi_var_b"):
            if col not in existing:
                conn.execute(text(f"ALTER TABLE nrfi_features ADD COLUMN {col} DOUBLE PRECISION"))
                added.append(col)

    if added:
        print(f"Added columns: {', '.join(added)}")
    else:
        print("Columns already exist — nothing to do.")


if __name__ == "__main__":
    main()
