"""
scripts/post_discord.py

Posts today's NRFI predictions to a Discord channel via webhook.

Reads predictions directly from the DB (same source as the API) and formats
them as Discord embeds — one per game, color-coded by edge.

Usage:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... python scripts/post_discord.py
    DISCORD_WEBHOOK_URL=... python scripts/post_discord.py --date 2026-04-01

Requires DISCORD_WEBHOOK_URL in environment. If not set, exits silently.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from typing import Any

import requests

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal
from backend.modeling.predict import predict_for_game

# Discord embed color integers (RGB hex)
_COLOR_GREEN = 0x2ECC71   # positive edge
_COLOR_RED = 0xE74C3C     # negative edge
_COLOR_GRAY = 0x95A5A6    # no market data
_COLOR_BLUE = 0x3498DB    # header

# Webhook payload limit: 10 embeds per request
_MAX_EMBEDS_PER_REQUEST = 10

# Edge threshold for a "strong" recommendation (same default as post_results.py)
_VALUE_PLAY_THRESHOLD = float(os.environ.get("VALUE_PLAY_THRESHOLD_PP", "2")) / 100.0


def _edge_color(edge: float | None) -> int:
    if edge is None:
        return _COLOR_GRAY
    return _COLOR_GREEN if edge >= 0 else _COLOR_RED


def _recommendation(edge: float, model: float) -> str:
    """Plain-English read on whether to bet NRFI, lean NRFI, or fade."""
    nrfi_pct = f"{model * 100:.0f}%"
    yrfi_pct = f"{(1 - model) * 100:.0f}%"
    edge_pct = f"{abs(edge) * 100:.0f}%"

    if edge >= _VALUE_PLAY_THRESHOLD:
        return (
            f"🟢 **Bet NRFI** — our model gives NRFI a {nrfi_pct} chance "
            f"vs the market's implied probability. We see {edge_pct} of extra value here."
        )
    elif edge > 0:
        return (
            f"🟡 **Lean NRFI** — our model gives NRFI a {nrfi_pct} chance. "
            f"Slight edge over the market, but not a strong value play."
        )
    elif edge > -_VALUE_PLAY_THRESHOLD:
        return (
            f"🟡 **Lean YRFI** — our model gives NRFI only a {nrfi_pct} chance "
            f"(YRFI {yrfi_pct}). Market is more confident in NRFI than we are."
        )
    else:
        return (
            f"🔴 **Fade NRFI** — our model gives NRFI only a {nrfi_pct} chance "
            f"(YRFI {yrfi_pct}). Market significantly overvalues NRFI by {edge_pct}."
        )


def _build_game_embed(pred: dict[str, Any]) -> dict:
    """Build a single Discord embed dict for one game prediction."""
    away = pred["away_team"]
    home = pred["home_team"]
    edge = pred.get("edge")
    model = pred.get("p_nrfi_model")
    market = pred.get("p_nrfi_market")

    if model is not None and market is not None and edge is not None:
        sign = "+" if edge >= 0 else ""
        data_line = f"Model {model * 100:.0f}% · Mkt {market * 100:.0f}% · Edge {sign}{edge * 100:.0f}%"
        rec_line = _recommendation(edge, model)
        description = f"{data_line}\n{rec_line}"
    elif model is not None:
        nrfi_pct = f"{model * 100:.0f}%"
        yrfi_pct = f"{(1 - model) * 100:.0f}%"
        description = (
            f"Model {nrfi_pct} · Mkt N/A · Edge N/A\n"
            f"⚪ No market lines yet — model gives NRFI a {nrfi_pct} chance (YRFI {yrfi_pct})."
        )
    else:
        description = "No prediction available."

    return {
        "title": f"{away} @ {home}",
        "description": description,
        "color": _edge_color(edge),
    }


def _build_header_embed(target_date: str, game_count: int) -> dict:
    return {
        "title": f"NRFI Picks — {target_date}",
        "description": f"{game_count} game(s) with predictions today.",
        "color": _COLOR_BLUE,
    }


def _post_payload(webhook_url: str, payload: dict) -> None:
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()


def post_predictions(target_date: str | None = None, webhook_url: str | None = None) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL not set — skipping Discord post.")
        return

    target = target_date or str(date.today())
    db = SessionLocal()

    try:
        games = db.query(Game).filter(Game.game_date == target).all()
        if not games:
            logger.info("No games found for %s — nothing to post.", target)
            return

        preds = []
        for game in games:
            pred = predict_for_game(game.id, db)
            if pred is not None:
                preds.append(pred)

        if not preds:
            logger.info("No predictions available for %s.", target)
            return

        logger.info("Posting %d predictions to Discord for %s.", len(preds), target)

        # Sort: highest edge first (None edge at the bottom)
        preds.sort(key=lambda p: (p["edge"] is None, -(p["edge"] or 0)))

        # Build all embeds: header + one per game
        header_embed = _build_header_embed(target, len(preds))
        game_embeds = [_build_game_embed(p) for p in preds]

        # First request: header + first batch of games
        first_batch = game_embeds[: _MAX_EMBEDS_PER_REQUEST - 1]
        _post_payload(webhook_url, {"embeds": [header_embed] + first_batch})

        # Any overflow (> 9 games): send in follow-up requests
        remaining = game_embeds[_MAX_EMBEDS_PER_REQUEST - 1 :]
        for i in range(0, len(remaining), _MAX_EMBEDS_PER_REQUEST):
            chunk = remaining[i : i + _MAX_EMBEDS_PER_REQUEST]
            _post_payload(webhook_url, {"embeds": chunk})

        logger.info("Discord post complete.")

    except requests.HTTPError as exc:
        logger.error("Discord webhook returned %s: %s", exc.response.status_code, exc.response.text)
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Post today's NRFI picks to Discord.")
    parser.add_argument("--date", default=None, help="Date in YYYY-MM-DD (default: today)")
    parser.add_argument("--webhook-url", default=None, help="Override DISCORD_WEBHOOK_URL env var")
    args = parser.parse_args()
    post_predictions(target_date=args.date, webhook_url=args.webhook_url)


if __name__ == "__main__":
    main()
