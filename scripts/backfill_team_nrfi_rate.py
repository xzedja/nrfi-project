"""
scripts/backfill_team_nrfi_rate.py

Backfills home_team_nrfi_rate_l30 and away_team_nrfi_rate_l30 for all existing
nrfi_features rows.  Run AFTER migrate_add_team_nrfi_rate.py.

For each game, computes the fraction of the team's last 30 games (cross-season,
strictly before the game date) that resulted in NRFI.  Requires >= 10 prior games;
NULL otherwise (imputed to median at train time by SeasonStartImputer).

Usage:
    docker exec -it nrfi-project-backend-1 python scripts/backfill_team_nrfi_rate.py
    docker exec -it nrfi-project-backend-1 python scripts/backfill_team_nrfi_rate.py --season 2026
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from sqlalchemy import extract, text

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal

_MIN_GAMES = 10
_WINDOW = 30


def _build_nrfi_history(db, years: list[int]) -> dict[str, list[tuple[date, bool]]]:
    """Return team → sorted [(game_date, nrfi)] for the given years."""
    rows = (
        db.query(Game.home_team, Game.away_team, Game.game_date, Game.nrfi)
        .filter(
            extract("year", Game.game_date).in_(years),
            Game.nrfi.isnot(None),
        )
        .order_by(Game.game_date)
        .all()
    )
    history: dict[str, list[tuple[date, bool]]] = {}
    for home, away, gdate, nrfi in rows:
        for team in (home, away):
            history.setdefault(team, []).append((gdate, bool(nrfi)))
    return history


def backfill(season: int | None = None) -> None:
    db = SessionLocal()
    try:
        # Load target feature rows
        q = db.query(NrfiFeatures, Game).join(Game, NrfiFeatures.game_id == Game.id)
        if season:
            q = q.filter(extract("year", Game.game_date) == season)
        rows = q.order_by(Game.game_date).all()

        if not rows:
            logger.info("No rows found — nothing to backfill.")
            return

        logger.info("Backfilling %d nrfi_features rows%s...",
                    len(rows), f" (season {season})" if season else "")

        # Determine years we need for cross-season history
        years_in_data = {row[1].game_date.year for row in rows}
        history_years = sorted({y for yr in years_in_data for y in (yr - 1, yr)})
        nrfi_history = _build_nrfi_history(db, history_years)

        updated = skipped = 0
        for feat, game in rows:
            # Skip if both already populated
            if feat.home_team_nrfi_rate_l30 is not None and feat.away_team_nrfi_rate_l30 is not None:
                skipped += 1
                continue

            for attr, team in (
                ("home_team_nrfi_rate_l30", game.home_team),
                ("away_team_nrfi_rate_l30", game.away_team),
            ):
                if getattr(feat, attr) is not None:
                    continue
                prior = [
                    nrfi for gdate, nrfi in nrfi_history.get(team, [])
                    if gdate < game.game_date
                ]
                last_n = prior[-_WINDOW:]
                if len(last_n) >= _MIN_GAMES:
                    setattr(feat, attr, round(sum(last_n) / len(last_n), 4))
                # else leave NULL — imputed to median at train time

            updated += 1
            if updated % 500 == 0:
                db.commit()
                logger.info("  %d rows updated so far...", updated)

        db.commit()
        logger.info("Done — updated: %d, skipped (already set): %d", updated, skipped)

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=None,
                        help="Restrict to one season (default: all seasons)")
    args = parser.parse_args()
    backfill(season=args.season)


if __name__ == "__main__":
    main()
