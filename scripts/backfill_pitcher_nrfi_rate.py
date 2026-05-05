"""
scripts/backfill_pitcher_nrfi_rate.py

Backfills home_sp_nrfi_rate_season and away_sp_nrfi_rate_season for all existing
nrfi_features rows.  Run AFTER migrate_add_pitcher_nrfi_rate.py.

For each game, computes the pitcher's fraction of current-season starts (strictly
before the game date) where they held the opponent scoreless in their half of the
first inning.  Requires >= 3 prior starts; NULL otherwise (imputed to home_sp_hold_rate
via SeasonStartImputer at train/predict time).

Uses DB data only (game_pitchers + games) — does not re-fetch Statcast.

Usage:
    docker exec -it nrfi-backend-1 python scripts/backfill_pitcher_nrfi_rate.py
    docker exec -it nrfi-backend-1 python scripts/backfill_pitcher_nrfi_rate.py --season 2026
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from sqlalchemy import extract

from backend.db.models import Game, GamePitchers, NrfiFeatures
from backend.db.session import SessionLocal

_MIN_STARTS = 3


def _build_pitcher_hold_history(
    db, years: list[int]
) -> tuple[dict[int, list[tuple[date, bool]]], dict[int, list[tuple[date, bool]]]]:
    """
    Return (home_history, away_history) where each maps pitcher DB id →
    sorted [(game_date, did_hold)] for games in the given years.

    For the home pitcher: did_hold = (inning_1_away_runs == 0)  — held top of 1st
    For the away pitcher: did_hold = (inning_1_home_runs == 0)  — held bottom of 1st
    """
    rows = (
        db.query(
            GamePitchers.home_sp_id,
            GamePitchers.away_sp_id,
            Game.game_date,
            Game.inning_1_home_runs,
            Game.inning_1_away_runs,
        )
        .join(Game, GamePitchers.game_id == Game.id)
        .filter(
            extract("year", Game.game_date).in_(years),
            Game.inning_1_home_runs.isnot(None),
            Game.inning_1_away_runs.isnot(None),
        )
        .order_by(Game.game_date)
        .all()
    )

    home_history: dict[int, list[tuple[date, bool]]] = defaultdict(list)
    away_history: dict[int, list[tuple[date, bool]]] = defaultdict(list)

    for home_sp_id, away_sp_id, game_date, h_runs, a_runs in rows:
        if home_sp_id is not None:
            home_history[home_sp_id].append((game_date, a_runs == 0))
        if away_sp_id is not None:
            away_history[away_sp_id].append((game_date, h_runs == 0))

    return dict(home_history), dict(away_history)


def backfill(season: int | None = None) -> None:
    db = SessionLocal()
    try:
        q = db.query(NrfiFeatures, Game, GamePitchers).join(
            Game, NrfiFeatures.game_id == Game.id
        ).join(
            GamePitchers, Game.id == GamePitchers.game_id
        )
        if season:
            q = q.filter(extract("year", Game.game_date) == season)
        rows = q.order_by(Game.game_date).all()

        if not rows:
            logger.info("No rows found — nothing to backfill.")
            return

        logger.info(
            "Backfilling %d nrfi_features rows%s...",
            len(rows), f" (season {season})" if season else "",
        )

        # Determine years we need — include the year of each row (same-season starts only)
        years_in_data = {row[1].game_date.year for row in rows}
        home_history, away_history = _build_pitcher_hold_history(db, list(years_in_data))

        updated = skipped = 0
        for feat, game, gp in rows:
            if feat.home_sp_nrfi_rate_season is not None and feat.away_sp_nrfi_rate_season is not None:
                skipped += 1
                continue

            game_year = game.game_date.year

            for attr, pitcher_id, history in (
                ("home_sp_nrfi_rate_season", gp.home_sp_id, home_history),
                ("away_sp_nrfi_rate_season", gp.away_sp_id, away_history),
            ):
                if getattr(feat, attr) is not None:
                    continue
                if pitcher_id is None:
                    continue

                prior = [
                    held
                    for gdate, held in history.get(pitcher_id, [])
                    if gdate < game.game_date and gdate.year == game_year
                ]

                if len(prior) >= _MIN_STARTS:
                    setattr(feat, attr, round(sum(prior) / len(prior), 4))
                # else leave NULL

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
