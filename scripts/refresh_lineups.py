"""
scripts/refresh_lineups.py

Fetches today's batting lineups and updates home_lineup_obp / away_lineup_obp
in nrfi_features for any games that don't have lineup data yet.

Intended to run hourly from 9 AM – 7 PM so predictions update as lineups
get posted throughout the day. No-op if all games already have lineup data.

No external API keys required — uses MLB Stats API (free/public) and
pybaseball (Fangraphs, cached locally).

Usage:
    python scripts/refresh_lineups.py
    python scripts/refresh_lineups.py --date 2026-04-05
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.data.fetch_lineups import update_lineup_obp_for_date
from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal


def refresh_lineups(target_date: str | None = None) -> None:
    target = target_date or str(date.today())

    # Check if any games still need lineup data
    db = SessionLocal()
    try:
        missing = (
            db.query(Game)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(
                Game.game_date == target,
                NrfiFeatures.home_lineup_obp.is_(None),
            )
            .count()
        )
    finally:
        db.close()

    if missing == 0:
        logger.info("All games for %s already have lineup data — nothing to do.", target)
        return

    logger.info("%d game(s) on %s still need lineup data — fetching...", missing, target)
    updated = update_lineup_obp_for_date(target)
    logger.info("Lineup refresh complete — updated %d game(s).", updated)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh batting lineups for today's games.")
    parser.add_argument("--date", default=None, help="Date in YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    refresh_lineups(target_date=args.date)


if __name__ == "__main__":
    main()
