"""
scripts/backfill_park_factors.py

Backfills the park_factor column in nrfi_features for all existing rows.

Previously, all rows had park_factor=1.0 (placeholder). This script computes
real first-inning park factors from historical game data and updates each row.

Park factor formula:
    raw_pf = avg_fi_runs_at_park / league_avg_fi_runs
    park_factor = regression_weight * raw_pf + (1 - regression_weight) * 1.0
    regression_weight = min(1.0, games_at_park / 200)

Anti-leakage: for a game in season Y, only prior-season data (< Y) is used.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_park_factors.py
    DATABASE_URL=postgresql://... python scripts/backfill_park_factors.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import extract, text

sys.path.insert(0, ".")

from backend.data.build_features import _precompute_park_factors
from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def backfill(dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        # Find all seasons that have nrfi_features rows
        seasons_result = db.execute(
            text("""
                SELECT DISTINCT EXTRACT(YEAR FROM g.game_date)::int AS season
                FROM nrfi_features nf
                JOIN games g ON g.id = nf.game_id
                ORDER BY season
            """)
        )
        seasons = [row[0] for row in seasons_result]
        logger.info("Found %d seasons to backfill: %s", len(seasons), seasons)

        total_updated = 0

        for season in seasons:
            logger.info("--- Season %s ---", season)

            park_factors = _precompute_park_factors(db, before_season=season)

            if not park_factors:
                logger.warning("  No prior-season park data found for season %s — skipping.", season)
                continue

            # Fetch all (nrfi_features.id, game.park) for this season
            rows = (
                db.query(NrfiFeatures.id, Game.park)
                .join(Game, NrfiFeatures.game_id == Game.id)
                .filter(extract("year", Game.game_date) == season)
                .all()
            )

            updated = 0
            unchanged = 0
            for feat_id, park in rows:
                pf = park_factors.get(park, 1.0)
                if dry_run:
                    logger.debug("  [dry-run] features id=%d  park=%s  park_factor=%.4f", feat_id, park, pf)
                else:
                    db.execute(
                        text("UPDATE nrfi_features SET park_factor = :pf WHERE id = :id"),
                        {"pf": pf, "id": feat_id},
                    )
                if pf != 1.0:
                    updated += 1
                else:
                    unchanged += 1

            if not dry_run:
                db.commit()

            logger.info(
                "  Season %s — %d rows with non-neutral park factor, %d rows at 1.0 (unknown/neutral park)",
                season, updated, unchanged,
            )
            total_updated += updated + unchanged

        action = "[dry-run] would update" if dry_run else "updated"
        logger.info("Done. Total rows %s: %d", action, total_updated)

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill park_factor in nrfi_features.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and log values without writing to DB.",
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
