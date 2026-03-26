"""
scripts/backfill_umpire_assignments.py

Fetches historical HP umpire assignments from the MLB Stats API and stores
them in the game_umpires table for all games that don't yet have a row.

Strategy: iterate by date (one schedule API call per game day), which is far
more efficient than one boxscore call per game. Falls back to the boxscore
endpoint for any games that the schedule hydrate doesn't cover.

This also updates the ump_nrfi_rate_above_avg column in nrfi_features once
all assignments are stored (requires a separate backfill step — see notes).

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_umpire_assignments.py
    DATABASE_URL=postgresql://... python scripts/backfill_umpire_assignments.py --season 2023
    DATABASE_URL=postgresql://... python scripts/backfill_umpire_assignments.py --dry-run

After running this, backfill the ump_nrfi_rate_above_avg feature with:
    DATABASE_URL=postgresql://... python scripts/backfill_ump_features.py
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta

from sqlalchemy import extract, text

sys.path.insert(0, ".")

from backend.data.fetch_umpire import fetch_umpires_for_date, fetch_umpire_for_game_pk
from backend.db.models import Game, GameUmpire
from backend.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_MLB_SEASON_RANGES = {
    2015: ("2015-04-05", "2015-10-04"),
    2016: ("2016-04-03", "2016-10-02"),
    2017: ("2017-04-02", "2017-10-01"),
    2018: ("2018-03-29", "2018-10-01"),
    2019: ("2019-03-28", "2019-09-29"),
    2020: ("2020-07-23", "2020-09-27"),  # COVID short season
    2021: ("2021-04-01", "2021-10-03"),
    2022: ("2022-04-07", "2022-10-05"),
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-20", "2024-09-29"),
    2025: ("2025-03-27", "2025-09-28"),
}


def _iter_dates(start: str, end: str):
    d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    while d <= end_d:
        yield str(d)
        d += timedelta(days=1)


def backfill(season: int | None = None, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        # Find all games without a GameUmpire row
        missing_q = (
            db.query(Game)
            .outerjoin(GameUmpire, Game.id == GameUmpire.game_id)
            .filter(GameUmpire.id.is_(None))
            .filter(Game.external_id.isnot(None))
        )
        if season:
            missing_q = missing_q.filter(extract("year", Game.game_date) == season)

        missing_games = missing_q.order_by(Game.game_date).all()
        logger.info("Found %d games missing umpire assignments.", len(missing_games))

        if not missing_games:
            logger.info("Nothing to do.")
            return

        # Build lookup: external_id → Game
        ext_id_to_game: dict[int, Game] = {g.external_id: g for g in missing_games}

        # Determine date range to iterate
        dates_needed = sorted({str(g.game_date) for g in missing_games})
        logger.info("Iterating %d dates...", len(dates_needed))

        inserted = 0
        not_found = 0

        for date_str in dates_needed:
            ump_map = fetch_umpires_for_date(date_str)
            time.sleep(0.1)  # gentle rate limiting

            for game_pk, ump_info in ump_map.items():
                game = ext_id_to_game.get(game_pk)
                if game is None:
                    continue  # game not in our "missing" set
                if not dry_run:
                    db.add(GameUmpire(
                        game_id=game.id,
                        ump_id=ump_info["ump_id"],
                        ump_name=ump_info.get("ump_name"),
                    ))
                    ext_id_to_game.pop(game_pk)  # mark as handled
                inserted += 1

            if not dry_run:
                db.commit()

        # Fallback: any remaining games not covered by schedule hydrate
        remaining = list(ext_id_to_game.values())
        if remaining:
            logger.info(
                "  %d games not found via schedule hydrate — trying boxscore fallback...",
                len(remaining),
            )
            for game in remaining:
                ump_info = fetch_umpire_for_game_pk(game.external_id)
                time.sleep(0.05)
                if ump_info:
                    if not dry_run:
                        db.add(GameUmpire(
                            game_id=game.id,
                            ump_id=ump_info["ump_id"],
                            ump_name=ump_info.get("ump_name"),
                        ))
                    inserted += 1
                else:
                    not_found += 1

            if not dry_run:
                db.commit()

        action = "[dry-run] would insert" if dry_run else "inserted"
        logger.info(
            "Done. %s %d umpire assignments. %d games had no umpire data.",
            action, inserted, not_found,
        )

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill HP umpire assignments into game_umpires.")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(season=args.season, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
