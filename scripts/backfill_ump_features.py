"""
scripts/backfill_ump_features.py

Backfills ump_nrfi_rate_above_avg in nrfi_features for all existing rows,
using umpire assignments already stored in game_umpires.

Run AFTER backfill_umpire_assignments.py.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_ump_features.py
    DATABASE_URL=postgresql://... python scripts/backfill_ump_features.py --season 2023
    DATABASE_URL=postgresql://... python scripts/backfill_ump_features.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from bisect import bisect_left
from datetime import date

from sqlalchemy import extract, text

sys.path.insert(0, ".")

from backend.db.models import Game, GameUmpire, NrfiFeatures
from backend.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def backfill(season: int | None = None, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        # Load all historical umpire game results for computing prior rates
        all_ump_rows = (
            db.query(GameUmpire.ump_id, Game.game_date, Game.nrfi)
            .join(Game, GameUmpire.game_id == Game.id)
            .filter(Game.nrfi.isnot(None))
            .order_by(Game.game_date)
            .all()
        )

        if not all_ump_rows:
            logger.warning("No GameUmpire rows found. Run backfill_umpire_assignments.py first.")
            return

        logger.info("Loaded %d historical umpire-game records.", len(all_ump_rows))

        # Build per-umpire sorted history
        ump_history: dict[int, list[tuple[date, bool]]] = {}
        total_nrfi = 0
        total_games = 0
        for ump_id, game_date, nrfi_label in all_ump_rows:
            ump_history.setdefault(ump_id, []).append((game_date, bool(nrfi_label)))
            total_nrfi += int(nrfi_label)
            total_games += 1

        league_avg_nrfi = total_nrfi / total_games if total_games > 0 else 0.5
        logger.info("League-avg NRFI rate across all umpired games: %.4f", league_avg_nrfi)

        # Load target rows: nrfi_features joined with umpire assignment
        target_q = (
            db.query(NrfiFeatures.id, GameUmpire.ump_id, Game.game_date)
            .join(Game, NrfiFeatures.game_id == Game.id)
            .join(GameUmpire, GameUmpire.game_id == Game.id)
        )
        if season:
            target_q = target_q.filter(extract("year", Game.game_date) == season)

        target_rows = target_q.order_by(Game.game_date).all()
        logger.info("Computing ump feature for %d nrfi_features rows.", len(target_rows))

        updated = 0
        no_prior = 0

        for feat_id, ump_id, game_date in target_rows:
            history = ump_history.get(ump_id, [])
            idx = bisect_left(history, (game_date,))
            prior = history[:idx]

            if not prior:
                no_prior += 1
                continue

            n = len(prior)
            nrfi_count = sum(1 for _, label in prior if label)
            ump_rate = nrfi_count / n
            weight = min(1.0, n / 150.0)
            ump_feature = round(weight * (ump_rate - league_avg_nrfi), 4)

            if not dry_run:
                db.execute(
                    text("UPDATE nrfi_features SET ump_nrfi_rate_above_avg = :val WHERE id = :id"),
                    {"val": ump_feature, "id": feat_id},
                )
            updated += 1

        if not dry_run:
            db.commit()

        action = "[dry-run] would update" if dry_run else "updated"
        logger.info(
            "Done. %s %d rows. %d had no prior umpire history (left NULL).",
            action, updated, no_prior,
        )

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill ump_nrfi_rate_above_avg in nrfi_features.")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(season=args.season, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
