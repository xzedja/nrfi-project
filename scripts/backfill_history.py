"""
scripts/backfill_history.py

Backfills historical MLB data (2015–present) into the database.

For each season in the given range, fetches:
  - Game results with 1st-inning run totals (via Statcast)
  - Starting pitcher identities per game

Then inserts or updates:
  - Game rows (keyed on external_id / game_pk)
  - Pitcher rows (keyed on external_id)
  - GamePitchers rows linking starters to games

All inserts are idempotent — existing rows are skipped, not duplicated.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_history.py
    DATABASE_URL=postgresql://... python scripts/backfill_history.py --start 2018 --end 2023
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.data.fetch_stats import load_games_for_season, load_starting_pitchers_for_season
from backend.db.models import Game, GamePitchers, Pitcher
from backend.db.session import SessionLocal

DEFAULT_START = 2015
DEFAULT_END = date.today().year


def _upsert_pitcher(db, external_id: int, throws: str | None) -> Pitcher:
    """Return existing Pitcher or create a minimal new one."""
    pitcher = db.query(Pitcher).filter_by(external_id=external_id).first()
    if pitcher is None:
        pitcher = Pitcher(external_id=external_id, throws=throws)
        db.add(pitcher)
        db.flush()  # populate pitcher.id without committing
    return pitcher


def backfill_season(season: int) -> None:
    logger.info("=== Backfilling season %s ===", season)

    games = load_games_for_season(season)
    sp_map = load_starting_pitchers_for_season(season)

    logger.info("  %d games fetched from Statcast", len(games))

    db = SessionLocal()
    try:
        inserted_games = 0
        skipped_games = 0

        for g in games:
            game_pk: int = g["game_pk"]

            # Check for existing row by MLB game_pk
            existing = db.query(Game).filter_by(external_id=game_pk).first()
            if existing is not None:
                skipped_games += 1
                continue

            game = Game(
                external_id=game_pk,
                game_date=date.fromisoformat(g["game_date"]),
                home_team=g["home_team"],
                away_team=g["away_team"],
                inning_1_home_runs=g["inning_1_home_runs"],
                inning_1_away_runs=g["inning_1_away_runs"],
                nrfi=bool(g["nrfi"]),
            )
            db.add(game)
            db.flush()  # populate game.id

            # Link starting pitchers if available for this game
            sp = sp_map.get(game_pk)
            if sp:
                home_sp = None
                away_sp = None

                if sp["home_sp_id"] is not None:
                    home_sp = _upsert_pitcher(db, sp["home_sp_id"], sp["home_sp_throws"])
                if sp["away_sp_id"] is not None:
                    away_sp = _upsert_pitcher(db, sp["away_sp_id"], sp["away_sp_throws"])

                db.add(GamePitchers(
                    game_id=game.id,
                    home_sp_id=home_sp.id if home_sp else None,
                    away_sp_id=away_sp.id if away_sp else None,
                ))

            inserted_games += 1

        db.commit()
        logger.info(
            "  Season %s done — inserted: %d, skipped (already existed): %d",
            season, inserted_games, skipped_games,
        )

    except Exception:
        db.rollback()
        logger.exception("  Error during backfill for season %s — rolled back.", season)
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical NRFI data.")
    parser.add_argument("--start", type=int, default=DEFAULT_START, help="First season to backfill")
    parser.add_argument("--end", type=int, default=DEFAULT_END, help="Last season to backfill (inclusive)")
    args = parser.parse_args()

    for season in range(args.start, args.end + 1):
        backfill_season(season)

    logger.info("Backfill complete.")


if __name__ == "__main__":
    main()
