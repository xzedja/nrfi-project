"""
scripts/post_results.py

Posts yesterday's NRFI pick results + season record to Discord.

A "pick" is defined by edge, not raw probability (since p_nrfi_model > 0.5
for nearly every game):

  All plays:   edge > 0       (model sees any value vs market)
  Value plays: edge > VALUE_PLAY_THRESHOLD_PP  (clear edge, default +2 pp)

Win = picked NRFI (edge > 0) and game was NRFI.
Loss = picked NRFI (edge > 0) and game was YRFI.

Run each morning before today's picks are posted so Discord shows:
  1. Yesterday's results
  2. Today's picks

Usage:
    python scripts/post_results.py
    python scripts/post_results.py --date 2026-04-05   # score a specific date
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta

import requests

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal
from scripts.post_discord import _post_payload

# Edge threshold (in probability, not pp) for "value plays"
_VALUE_PLAY_THRESHOLD = float(os.environ.get("VALUE_PLAY_THRESHOLD_PP", "2")) / 100.0

_COLOR_GREEN  = 0x2ECC71
_COLOR_RED    = 0xE74C3C
_COLOR_GOLD   = 0xF1C40F
_COLOR_BLUE   = 0x3498DB
_COLOR_GRAY   = 0x95A5A6


def _win_loss_str(wins: int, losses: int) -> str:
    total = wins + losses
    pct = (wins / total * 100) if total > 0 else 0.0
    return f"{wins}-{losses} ({pct:.1f}%)"


def post_results(target_date: str | None = None) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL not set — skipping results post.")
        return

    # Default: score yesterday's games
    score_date = target_date or str(date.today() - timedelta(days=1))

    db = SessionLocal()
    try:
        # Fetch games from score_date that have both a stored prediction and an outcome
        rows = (
            db.query(Game, NrfiFeatures)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(
                Game.game_date == score_date,
                NrfiFeatures.nrfi_label.isnot(None),
                NrfiFeatures.p_nrfi_model.isnot(None),
            )
            .order_by(Game.game_date)
            .all()
        )

        if not rows:
            logger.info("No completed results found for %s — skipping.", score_date)
            return

        # Score yesterday's games
        yesterday_lines = []
        yday_all_w = yday_all_l = 0
        yday_val_w = yday_val_l = 0

        for game, feat in rows:
            edge = (
                feat.p_nrfi_model - feat.p_nrfi_market
                if feat.p_nrfi_market is not None
                else None
            )
            if edge is None or edge <= 0:
                continue  # no pick on negative or missing edge

            actual_nrfi = bool(feat.nrfi_label)
            won = actual_nrfi
            result_icon = "✅" if won else "❌"
            outcome_str = "NRFI ✓" if actual_nrfi else "YRFI"
            model_pct = f"{feat.p_nrfi_model * 100:.0f}%"
            mkt_pct = f"{feat.p_nrfi_market * 100:.0f}%"
            edge_pct = f"+{edge * 100:.0f}%"

            yesterday_lines.append(
                f"{result_icon} {game.away_team} @ {game.home_team} — {outcome_str}"
                f"  |  Model {model_pct} · Mkt {mkt_pct} · Edge {edge_pct}"
            )

            yday_all_w += int(won)
            yday_all_l += int(not won)

            if edge >= _VALUE_PLAY_THRESHOLD:
                yday_val_w += int(won)
                yday_val_l += int(not won)

        if not yesterday_lines:
            logger.info("No positive-edge picks found for %s — skipping.", score_date)
            return

        # Compute season-to-date records (all dates up to and including score_date)
        season_rows = (
            db.query(Game, NrfiFeatures)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(
                Game.game_date <= score_date,
                NrfiFeatures.nrfi_label.isnot(None),
                NrfiFeatures.p_nrfi_model.isnot(None),
                NrfiFeatures.p_nrfi_market.isnot(None),
            )
            .all()
        )

        season_all_w = season_all_l = 0
        season_val_w = season_val_l = 0

        for game, feat in season_rows:
            edge = feat.p_nrfi_model - feat.p_nrfi_market
            if edge <= 0:
                continue
            won = bool(feat.nrfi_label)
            season_all_w += int(won)
            season_all_l += int(not won)
            if edge >= _VALUE_PLAY_THRESHOLD:
                season_val_w += int(won)
                season_val_l += int(not won)

    finally:
        db.close()

    # Build Discord embeds
    yday_record_str = _win_loss_str(yday_all_w, yday_all_l)
    game_list = "\n".join(yesterday_lines)

    yesterday_embed = {
        "title": f"Yesterday's Results — {score_date}",
        "description": f"{game_list}\n\n**Yesterday:** {yday_record_str}",
        "color": _COLOR_GREEN if yday_all_w >= yday_all_l else _COLOR_RED,
    }

    val_threshold_str = f"+{_VALUE_PLAY_THRESHOLD * 100:.0f}%"
    season_embed = {
        "title": "Season Record",
        "color": _COLOR_GOLD,
        "fields": [
            {
                "name": "All Plays (model > market)",
                "value": _win_loss_str(season_all_w, season_all_l),
                "inline": True,
            },
            {
                "name": f"Value Plays (edge > {val_threshold_str})",
                "value": _win_loss_str(season_val_w, season_val_l),
                "inline": True,
            },
        ],
    }

    try:
        _post_payload(webhook_url, {"embeds": [yesterday_embed, season_embed]})
        logger.info("Results posted to Discord for %s.", score_date)
    except requests.HTTPError as exc:
        logger.error("Discord webhook returned %s: %s", exc.response.status_code, exc.response.text)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Post yesterday's NRFI results to Discord.")
    parser.add_argument("--date", default=None, help="Score this date instead of yesterday (YYYY-MM-DD)")
    args = parser.parse_args()
    post_results(target_date=args.date)


if __name__ == "__main__":
    main()
