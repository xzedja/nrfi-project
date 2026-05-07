"""
scripts/refresh_results.py

Intraday first-inning results refresh for today's games.

Checks today's games where the first inning is already complete (either the
full game is Final, or the game is Live and past the 1st inning) and writes
the result to the DB.

Runs every 30 minutes via cron during the day. No-op if all today's games
already have results or if no games have started.

Usage:
    python scripts/refresh_results.py
    python scripts/refresh_results.py --date 2026-05-06
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date

import requests
from sqlalchemy import text

sys.path.insert(0, ".")

from backend.db.models import Game
from backend.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    "?sportId=1&date={date}&hydrate=linescore"
)
_REQUEST_TIMEOUT = 10


def _fetch_first_inning_map(date_str: str) -> dict[int, dict]:
    """
    Return {game_pk: {"home": int, "away": int}} for games on date_str
    where the first inning is complete.

    Includes both:
    - Final games (whole game done)
    - Live games where currentInning >= 2 (first inning finished)
    """
    url = _SCHEDULE_URL.format(date=date_str)
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch linescore data for %s: %s", date_str, exc)
        return {}

    result: dict[int, dict] = {}
    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            status = game.get("status", {})
            abstract_state = status.get("abstractGameState", "")

            # Accept Final games or Live games past the 1st inning
            if abstract_state == "Final":
                first_inn_done = True
            elif abstract_state == "Live":
                linescore = game.get("linescore", {})
                current_inning = linescore.get("currentInning", 0)
                first_inn_done = current_inning >= 2
            else:
                # Preview, Postponed, Suspended, etc.
                continue

            if not first_inn_done:
                continue

            game_pk = game.get("gamePk")
            linescore = game.get("linescore", {})
            innings = linescore.get("innings", [])

            if not innings:
                logger.debug("No innings data for game %s — skipping.", game_pk)
                continue

            first_inn = innings[0]
            home_runs = first_inn.get("home", {}).get("runs")
            away_runs = first_inn.get("away", {}).get("runs")

            if home_runs is None or away_runs is None:
                logger.debug("Missing first-inning run data for game %s — skipping.", game_pk)
                continue

            result[int(game_pk)] = {"home": int(home_runs), "away": int(away_runs)}

    return result


def refresh(target_date: str | None = None) -> None:
    target = target_date or str(date.today())

    db = SessionLocal()
    try:
        # Only look at today's games that don't have a result yet
        pending = (
            db.query(Game)
            .filter(
                Game.game_date == target,
                Game.nrfi.is_(None),
                Game.external_id.isnot(None),
            )
            .all()
        )

        if not pending:
            logger.info("All games for %s already have first-inning results — nothing to do.", target)
            return

        logger.info("%d game(s) still need first-inning results for %s.", len(pending), target)

        linescore_map = _fetch_first_inning_map(target)
        time.sleep(0.1)

        updated = 0
        for game in pending:
            scores = linescore_map.get(game.external_id)
            if scores is None:
                logger.debug(
                    "  %s @ %s — first inning not yet complete.",
                    game.away_team, game.home_team,
                )
                continue

            home_runs = scores["home"]
            away_runs = scores["away"]
            nrfi = (home_runs == 0) and (away_runs == 0)

            db.execute(
                text(
                    "UPDATE games SET "
                    "inning_1_home_runs = :home, "
                    "inning_1_away_runs = :away, "
                    "nrfi = :nrfi "
                    "WHERE id = :id"
                ),
                {"home": home_runs, "away": away_runs, "nrfi": nrfi, "id": game.id},
            )
            # Sync nrfi_label on features row if it exists
            db.execute(
                text("UPDATE nrfi_features SET nrfi_label = :nrfi WHERE game_id = :game_id"),
                {"nrfi": nrfi, "game_id": game.id},
            )

            logger.info(
                "  %s @ %s — 1st inn: away %d, home %d → NRFI=%s",
                game.away_team, game.home_team, away_runs, home_runs, nrfi,
            )
            updated += 1

        db.commit()
        logger.info("Updated %d / %d game(s) for %s.", updated, len(pending), target)

    except Exception:
        db.rollback()
        logger.exception("refresh_results failed — rolled back.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Refresh first-inning results for today's games.")
    parser.add_argument("--date", default=None, help="Date in YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    refresh(target_date=args.date)
