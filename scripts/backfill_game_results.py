"""
scripts/backfill_game_results.py

Fetches first-inning run data for completed games and writes it to:
  - games: inning_1_home_runs, inning_1_away_runs, nrfi
  - nrfi_features: nrfi_label

Targets all games where nrfi IS NULL and game_date < today (i.e. game should
have been played). Safe to re-run — idempotent.

Used two ways:
  1. Nightly cron job (run after all West Coast games finish, e.g. 2 AM ET)
  2. One-time catch-up for any missed days

Usage:
    python scripts/backfill_game_results.py
    python scripts/backfill_game_results.py --date 2026-04-05   # single date
    python scripts/backfill_game_results.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from datetime import date

import requests
from sqlalchemy import text

sys.path.insert(0, ".")

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    "?sportId=1&date={date}&hydrate=linescore"
)
_REQUEST_TIMEOUT = 10


def _fetch_linescore_map(date_str: str) -> dict[int, dict]:
    """
    Return {game_pk: {"home": int, "away": int}} for all *final* games on date_str.
    Games that are not yet final (in-progress, postponed, etc.) are excluded.
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
            # Only process games with a final status code
            status_code = status.get("statusCode", "")
            abstract_state = status.get("abstractGameState", "")
            if abstract_state != "Final":
                logger.debug(
                    "  Skipping game %s — status: %s (%s)",
                    game.get("gamePk"), abstract_state, status_code,
                )
                continue

            game_pk = game.get("gamePk")
            linescore = game.get("linescore", {})
            innings = linescore.get("innings", [])

            if not innings:
                logger.debug("  No linescore innings for game %s — skipping.", game_pk)
                continue

            first_inn = innings[0]
            home_runs = first_inn.get("home", {}).get("runs")
            away_runs = first_inn.get("away", {}).get("runs")

            if home_runs is None or away_runs is None:
                logger.debug(
                    "  Missing first-inning run data for game %s — skipping.", game_pk
                )
                continue

            result[int(game_pk)] = {"home": int(home_runs), "away": int(away_runs)}

    return result


def backfill(target_date: str | None = None, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        today = date.today()

        if target_date:
            # Single date mode
            games_to_fill = (
                db.query(Game)
                .filter(
                    Game.nrfi.is_(None),
                    Game.external_id.isnot(None),
                    Game.game_date == date.fromisoformat(target_date),
                )
                .all()
            )
        else:
            # All incomplete games before today
            games_to_fill = (
                db.query(Game)
                .filter(
                    Game.nrfi.is_(None),
                    Game.external_id.isnot(None),
                    Game.game_date < today,
                )
                .order_by(Game.game_date)
                .all()
            )

        logger.info("Found %d games with missing results.", len(games_to_fill))
        if not games_to_fill:
            logger.info("Nothing to do.")
            return

        # Group by date to batch API calls
        date_to_games: dict[str, list[Game]] = defaultdict(list)
        for g in games_to_fill:
            date_to_games[str(g.game_date)].append(g)

        logger.info("Fetching linescores for %d unique date(s)...", len(date_to_games))

        updated = 0
        skipped_not_final = 0
        skipped_no_data = 0

        for date_str, games_on_date in sorted(date_to_games.items()):
            linescore_map = _fetch_linescore_map(date_str)
            time.sleep(0.1)  # be polite to the MLB API

            for game in games_on_date:
                scores = linescore_map.get(game.external_id)
                if scores is None:
                    skipped_not_final += 1
                    continue

                home_runs = scores["home"]
                away_runs = scores["away"]
                nrfi = (home_runs == 0) and (away_runs == 0)

                if not dry_run:
                    # Update games table
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

                    # Update nrfi_features.nrfi_label if a features row exists
                    db.execute(
                        text(
                            "UPDATE nrfi_features SET nrfi_label = :nrfi "
                            "WHERE game_id = :game_id"
                        ),
                        {"nrfi": nrfi, "game_id": game.id},
                    )

                logger.debug(
                    "  %s %s vs %s — 1st inn: home %d, away %d → NRFI=%s",
                    date_str, game.home_team, game.away_team,
                    home_runs, away_runs, nrfi,
                )
                updated += 1

            if not dry_run:
                db.commit()
            logger.info(
                "  %s: updated %d game(s) so far (this date).",
                date_str,
                sum(1 for g in games_on_date if linescore_map.get(g.external_id) is not None),
            )

        action = "[dry-run] would update" if dry_run else "updated"
        logger.info(
            "Done. %s %d game(s). %d not final / not found.",
            action, updated, skipped_not_final,
        )

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill in first-inning results for completed games."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Only process games on this date (YYYY-MM-DD). Default: all past games.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would change, no writes.")
    args = parser.parse_args()
    backfill(target_date=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
