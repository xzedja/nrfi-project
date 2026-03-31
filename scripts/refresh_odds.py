"""
scripts/refresh_odds.py

Re-fetches today's odds and posts a Discord update for any games that
previously had no market data (N/A edge) but now have odds available.

Intended to run at noon to catch West Coast games whose lines weren't
posted yet at the 9 AM pipeline run.

No-op if all games already have odds or if no new odds came in.

Usage:
    python scripts/refresh_odds.py
    python scripts/refresh_odds.py --date 2026-04-05
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

import requests

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.data.fetch_lineups import update_lineup_obp_for_date
from backend.data.fetch_odds import fetch_and_store_odds
from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal
from backend.modeling.predict import predict_for_game
from scripts.post_discord import _build_game_embed, _build_header_embed, _post_payload

_COLOR_YELLOW = 0xF1C40F


def refresh(target_date: str | None = None) -> None:
    target = target_date or str(date.today())

    db = SessionLocal()
    try:
        # Find today's games that currently have no market probability
        games_without_odds = (
            db.query(Game)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(
                Game.game_date == target,
                NrfiFeatures.p_nrfi_market.is_(None),
            )
            .all()
        )

        if not games_without_odds:
            logger.info("All games for %s already have odds — nothing to do.", target)
            return

        no_odds_ids = {g.id for g in games_without_odds}
        logger.info(
            "%d game(s) have no odds yet for %s — re-fetching...",
            len(no_odds_ids), target,
        )
    finally:
        db.close()

    # Re-fetch odds (updates nrfi_features.p_nrfi_market in place)
    try:
        fetch_and_store_odds(date_str=target)
    except Exception:
        logger.exception("Odds fetch failed — aborting refresh.")
        return

    # Also refresh lineup OBP now that lineups are likely posted
    try:
        update_lineup_obp_for_date(target)
    except Exception:
        logger.warning("Lineup OBP refresh failed — continuing with odds update.")

    # Check which previously-empty games now have odds
    db = SessionLocal()
    try:
        newly_filled = (
            db.query(Game)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(
                Game.id.in_(no_odds_ids),
                NrfiFeatures.p_nrfi_market.isnot(None),
            )
            .all()
        )

        if not newly_filled:
            logger.info("No new odds came in for %s — nothing to post.", target)
            return

        logger.info(
            "%d game(s) now have odds — posting update to Discord.", len(newly_filled)
        )

        # Build predictions for newly-filled games only
        preds = []
        for game in newly_filled:
            pred = predict_for_game(game.id, db)
            if pred is not None:
                preds.append(pred)

        if not preds:
            logger.info("No predictions available — skipping Discord post.")
            return

        preds.sort(key=lambda p: (p["edge"] is None, -(p["edge"] or 0)))

        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not webhook_url:
            logger.info("DISCORD_WEBHOOK_URL not set — skipping Discord post.")
            return

        # Header indicating this is a late odds update
        header = {
            "title": f"Odds Update — {target}",
            "description": f"Lines are now available for {len(preds)} game(s) that had N/A odds this morning.",
            "color": _COLOR_YELLOW,
        }
        game_embeds = [_build_game_embed(p) for p in preds]

        first_batch = game_embeds[:9]
        _post_payload(webhook_url, {"embeds": [header] + first_batch})

        remaining = game_embeds[9:]
        for i in range(0, len(remaining), 10):
            _post_payload(webhook_url, {"embeds": remaining[i:i + 10]})

        logger.info("Discord odds update posted for %s.", target)

    except requests.HTTPError as exc:
        logger.error("Discord webhook returned %s: %s", exc.response.status_code, exc.response.text)
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-fetch odds and post update for games with N/A edges.")
    parser.add_argument("--date", default=None, help="Date in YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    refresh(target_date=args.date)


if __name__ == "__main__":
    main()
