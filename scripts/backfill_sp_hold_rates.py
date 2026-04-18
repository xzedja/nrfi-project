"""
scripts/backfill_sp_hold_rates.py

Backfills home_sp_hold_rate and away_sp_hold_rate in the nrfi_features table
for all existing rows where the values are NULL.

Run AFTER scripts/migrate_add_sp_hold_rates.py.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_sp_hold_rates.py
"""

from __future__ import annotations

import logging
import sys
from datetime import date

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from sqlalchemy import extract

from backend.data.build_features import _precompute_pitcher_hold_rates
from backend.db.models import Game, GamePitchers, NrfiFeatures, Pitcher
from backend.db.session import SessionLocal


def backfill_hold_rates() -> None:
    db = SessionLocal()
    try:
        # Find all nrfi_features rows missing hold rates
        missing = (
            db.query(NrfiFeatures, Game)
            .join(Game, NrfiFeatures.game_id == Game.id)
            .filter(
                (NrfiFeatures.home_sp_hold_rate.is_(None)) |
                (NrfiFeatures.away_sp_hold_rate.is_(None))
            )
            .order_by(Game.game_date)
            .all()
        )

        if not missing:
            logger.info("No rows need backfilling — all hold rates already populated.")
            return

        logger.info("Found %d rows to backfill", len(missing))

        # Group by season to batch the hold-rate computation
        seasons: dict[int, list[tuple[NrfiFeatures, Game]]] = {}
        for feat, game in missing:
            yr = game.game_date.year
            seasons.setdefault(yr, []).append((feat, game))

        for season, rows in sorted(seasons.items()):
            logger.info("Processing season %d (%d rows)...", season, len(rows))

            # Collect pitcher external IDs for this season's games
            game_ids = [game.id for _, game in rows]
            gp_rows = (
                db.query(GamePitchers, Pitcher)
                .filter(GamePitchers.game_id.in_(game_ids))
                .outerjoin(Pitcher, GamePitchers.home_sp_id == Pitcher.id)
                .all()
            )

            # Collect all pitcher external IDs for this season
            ext_ids: set[int] = set()
            for feat, game in rows:
                gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
                if gp:
                    if gp.home_sp:
                        ext_ids.add(gp.home_sp.external_id)
                    if gp.away_sp:
                        ext_ids.add(gp.away_sp.external_id)

            if not ext_ids:
                continue

            hold_rates = _precompute_pitcher_hold_rates(db, list(ext_ids), season)
            logger.info("  Computed hold rates for %d pitchers", len(hold_rates))

            updated = 0
            for feat, game in rows:
                gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
                if not gp:
                    continue

                if feat.home_sp_hold_rate is None and gp.home_sp:
                    feat.home_sp_hold_rate = hold_rates.get(gp.home_sp.external_id)
                if feat.away_sp_hold_rate is None and gp.away_sp:
                    feat.away_sp_hold_rate = hold_rates.get(gp.away_sp.external_id)
                updated += 1

            db.commit()
            logger.info("  Season %d: updated %d rows", season, updated)

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    backfill_hold_rates()
