"""
scripts/backfill_game_parks.py

Populates Game.park for all historical games where it is currently NULL.

Uses the MLB Stats API schedule endpoint (hydrate=venue) — one request per
unique game date. This is the same API used in the daily pipeline, so venue
names will exactly match what fetch_today.py stores going forward.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_game_parks.py
    DATABASE_URL=postgresql://... python scripts/backfill_game_parks.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict

import requests
from sqlalchemy import text

sys.path.insert(0, ".")

from backend.db.models import Game
from backend.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    "?sportId=1&date={date}&hydrate=venue"
)
_REQUEST_TIMEOUT = 10


def _fetch_venue_map(date_str: str) -> dict[int, str]:
    """Return {game_pk: venue_name} for all games on date_str."""
    url = _SCHEDULE_URL.format(date=date_str)
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch venue data for %s: %s", date_str, exc)
        return {}

    result: dict[int, str] = {}
    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            game_pk = game.get("gamePk")
            venue_name = game.get("venue", {}).get("name")
            if game_pk and venue_name:
                result[int(game_pk)] = venue_name
    return result


def backfill(dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        # Find all games with NULL park that have a game_pk (external_id)
        null_park_games = (
            db.query(Game)
            .filter(Game.park.is_(None), Game.external_id.isnot(None))
            .order_by(Game.game_date)
            .all()
        )

        logger.info("Found %d games with NULL park.", len(null_park_games))
        if not null_park_games:
            logger.info("Nothing to do.")
            return

        # Group by date for batched API calls
        date_to_games: dict[str, list[Game]] = defaultdict(list)
        for g in null_park_games:
            date_to_games[str(g.game_date)].append(g)

        logger.info("Iterating %d unique dates...", len(date_to_games))

        updated = 0
        not_found = 0
        unknown_venue = 0

        for date_str, games_on_date in sorted(date_to_games.items()):
            venue_map = _fetch_venue_map(date_str)
            time.sleep(0.1)

            for game in games_on_date:
                venue = venue_map.get(game.external_id)
                if venue is None:
                    not_found += 1
                    continue

                if not dry_run:
                    db.execute(
                        text("UPDATE games SET park = :park WHERE id = :id"),
                        {"park": venue, "id": game.id},
                    )
                updated += 1

                from backend.data.fetch_weather import PARK_INFO
                if venue not in PARK_INFO:
                    unknown_venue += 1
                    logger.debug("  Venue not in PARK_INFO (weather will be NULL): '%s'", venue)

            if not dry_run:
                db.commit()

        action = "[dry-run] would update" if dry_run else "updated"
        logger.info(
            "Done. %s %d games. %d game_pks not found in MLB API. "
            "%d venue names not in PARK_INFO (weather will be NULL for those).",
            action, updated, not_found, unknown_venue,
        )

        if unknown_venue > 0:
            logger.info(
                "Tip: add unknown venue names to PARK_INFO in backend/data/fetch_weather.py"
            )

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate Game.park from MLB Stats API.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
