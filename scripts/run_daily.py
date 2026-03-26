"""
scripts/run_daily.py

Daily pipeline: fetches today's MLB schedule + probable starters, inserts
game and pitcher rows, then builds NrfiFeatures so the API can serve
predictions for today's games.

Run this each morning before the first game starts (e.g. 9–10 AM local time).
Re-running is safe — all steps are idempotent.

Usage:
    DATABASE_URL=postgresql://... python scripts/run_daily.py
    DATABASE_URL=postgresql://... python scripts/run_daily.py --date 2023-04-03
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.data.fetch_today import fetch_schedule
from backend.data.build_features import build_features_for_season
from backend.data.fetch_odds import fetch_and_store_odds
from backend.db.models import Game, GamePitchers, GameUmpire, Pitcher
from backend.db.session import SessionLocal
from scripts.post_discord import post_predictions
from scripts.post_results import post_results


def _upsert_pitcher(db, external_id: int, name: str | None, throws: str | None) -> Pitcher:
    """Return existing Pitcher row or create a new one."""
    pitcher = db.query(Pitcher).filter_by(external_id=external_id).first()
    if pitcher is None:
        pitcher = Pitcher(external_id=external_id, name=name, throws=throws)
        db.add(pitcher)
        db.flush()
    elif name and pitcher.name is None:
        pitcher.name = name  # backfill name if we now have it
    return pitcher


def run_daily(target_date: str | None = None) -> None:
    target = target_date or str(date.today())
    logger.info("=== Daily pipeline for %s ===", target)

    # -----------------------------------------------------------------------
    # Step 0: Post yesterday's results to Discord (non-fatal)
    # -----------------------------------------------------------------------
    try:
        post_results()
    except Exception:
        logger.warning("Results post failed — continuing with today's pipeline.")

    # -----------------------------------------------------------------------
    # Step 1: Fetch schedule + probable starters from MLB Stats API
    # -----------------------------------------------------------------------
    games = fetch_schedule(target)
    if not games:
        logger.info("No games found for %s — nothing to do.", target)
        return

    logger.info("Found %d games.", len(games))

    no_starters = [g for g in games if g["home_sp_id"] is None or g["away_sp_id"] is None]
    if no_starters:
        logger.warning(
            "%d game(s) have no probable starter announced yet — "
            "features will be skipped for those games.",
            len(no_starters),
        )

    # -----------------------------------------------------------------------
    # Step 2: Insert Game + GamePitchers rows
    # -----------------------------------------------------------------------
    db = SessionLocal()
    inserted = 0
    skipped = 0

    try:
        for g in games:
            existing = db.query(Game).filter_by(external_id=g["game_pk"]).first()
            if existing is not None:
                skipped += 1
                continue

            game = Game(
                external_id=g["game_pk"],
                game_date=date.fromisoformat(g["game_date"]),
                home_team=g["home_team"],
                away_team=g["away_team"],
                park=g.get("venue_name"),
                # Run data intentionally null — game hasn't been played yet
            )
            db.add(game)
            db.flush()

            home_sp = None
            away_sp = None

            if g["home_sp_id"] is not None:
                home_sp = _upsert_pitcher(db, g["home_sp_id"], g["home_sp_name"], None)
            if g["away_sp_id"] is not None:
                away_sp = _upsert_pitcher(db, g["away_sp_id"], g["away_sp_name"], None)

            db.add(GamePitchers(
                game_id=game.id,
                home_sp_id=home_sp.id if home_sp else None,
                away_sp_id=away_sp.id if away_sp else None,
            ))

            if g.get("hp_ump_id") is not None:
                db.add(GameUmpire(
                    game_id=game.id,
                    ump_id=g["hp_ump_id"],
                    ump_name=g.get("hp_ump_name"),
                ))

            inserted += 1

        db.commit()
        logger.info("Games inserted: %d  |  already existed: %d", inserted, skipped)

    except Exception:
        db.rollback()
        logger.exception("Error inserting games — rolled back.")
        raise
    finally:
        db.close()

    # -----------------------------------------------------------------------
    # Step 3: Build NrfiFeatures for today's new games
    # -----------------------------------------------------------------------
    season = int(target[:4])
    logger.info("Building features for season %s (new games only)...", season)
    build_features_for_season(season)

    # -----------------------------------------------------------------------
    # Step 4: Fetch odds and update p_nrfi_market
    # -----------------------------------------------------------------------
    logger.info("Fetching odds for %s...", target)
    try:
        fetch_and_store_odds(date_str=target)
    except Exception:
        # Odds failure is non-fatal — predictions still work without market data
        logger.warning("Odds fetch failed — predictions will have no edge values today.")

    # -----------------------------------------------------------------------
    # Step 5: Post predictions to Discord (non-fatal if webhook not configured)
    # -----------------------------------------------------------------------
    try:
        post_predictions(target_date=target)
    except Exception:
        logger.warning("Discord post failed — predictions are still available via API.")

    logger.info("Daily pipeline complete. API is ready for %s.", target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily NRFI pipeline.")
    parser.add_argument(
        "--date",
        default=None,
        help="Date to process in YYYY-MM-DD format (default: today)",
    )
    args = parser.parse_args()
    run_daily(target_date=args.date)


if __name__ == "__main__":
    main()