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
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.db.models import Game, GamePitchers, NrfiFeatures, Odds
from backend.db.session import SessionLocal
from backend.modeling.predict import predict_for_game

# Discord embed color integers (RGB hex)
_COLOR_GREEN  = 0x2ECC71   # strong positive edge (value play)
_COLOR_YELLOW = 0xF1C40F   # lean positive edge
_COLOR_RED    = 0xE74C3C   # negative edge
_COLOR_GRAY   = 0x95A5A6   # no market data
_COLOR_BLUE   = 0x3498DB   # header

# Webhook payload limit: 10 embeds per request
_MAX_EMBEDS_PER_REQUEST = 10

# Edge threshold for a "strong" recommendation (same default as post_results.py)
_VALUE_PLAY_THRESHOLD = float(os.environ.get("VALUE_PLAY_THRESHOLD_PP", "2")) / 100.0


def _edge_color(edge: float | None) -> int:
    if edge is None:
        return _COLOR_GRAY
    if edge >= _VALUE_PLAY_THRESHOLD:
        return _COLOR_GREEN
    if edge > 0:
        return _COLOR_YELLOW
    return _COLOR_RED


def _recommendation(edge: float, model: float) -> str:
    """Concise read on whether to bet NRFI, lean, or fade."""
    edge_pct = f"{abs(edge) * 100:.0f}%"

    if edge >= _VALUE_PLAY_THRESHOLD:
        return f"🟢 **Bet NRFI** — +{edge_pct} edge over market"
    elif edge > 0:
        return f"🟡 **Lean NRFI** — slight edge, not a strong value play"
    elif edge > -_VALUE_PLAY_THRESHOLD:
        return f"🟡 **Lean YRFI** — market more confident in NRFI than we are"
    else:
        return f"🔴 **Fade NRFI** — market overvalues NRFI by {edge_pct}"


def _fmt_odds(o: int | None) -> str:
    if o is None:
        return "N/A"
    return f"+{o}" if o > 0 else str(o)


_PT = ZoneInfo("America/Los_Angeles")


def _fmt_game_time(game_time_utc: str | None) -> str | None:
    """Convert ISO UTC game time string to 'H:MM AM/PM PT' format."""
    if not game_time_utc:
        return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(game_time_utc.replace("Z", "+00:00"))
        dt_pt = dt.astimezone(_PT)
        return dt_pt.strftime("%-I:%M %p PT")
    except Exception:
        return None


def _build_game_embed(pred: dict[str, Any]) -> dict:
    """Build a single Discord embed dict for one game prediction."""
    away = pred["away_team"]
    home = pred["home_team"]
    edge = pred.get("edge")
    model = pred.get("p_nrfi_model")
    market = pred.get("p_nrfi_market")
    away_sp = pred.get("away_sp_name")
    home_sp = pred.get("home_sp_name")
    nrfi_odds = pred.get("first_inn_under_odds")
    yrfi_odds = pred.get("first_inn_over_odds")
    game_time_str = _fmt_game_time(pred.get("game_time"))

    title = f"{away} @ {home}"
    if game_time_str:
        title += f"  ·  {game_time_str}"

    pitchers_line = f"{away_sp} vs {home_sp}\n" if away_sp and home_sp else ""

    if nrfi_odds is not None or yrfi_odds is not None:
        odds_line = f"NRFI {_fmt_odds(nrfi_odds)} · YRFI {_fmt_odds(yrfi_odds)}\n"
    else:
        odds_line = ""

    if model is not None and market is not None and edge is not None:
        sign = "+" if edge >= 0 else ""
        data_line = f"Model {model * 100:.0f}% · Mkt {market * 100:.0f}% · Edge {sign}{edge * 100:.0f}%"
        description = f"{pitchers_line}{odds_line}{data_line}\n{_recommendation(edge, model)}"
    elif model is not None:
        nrfi_pct = f"{model * 100:.0f}%"
        description = (
            f"{pitchers_line}{odds_line}Model {nrfi_pct} · Mkt N/A\n"
            f"⚪ No lines yet — model gives NRFI {nrfi_pct}"
        )
    else:
        description = "No prediction available."

    return {
        "title": title,
        "description": description,
        "color": _edge_color(edge),
    }


def _build_header_embed(target_date: str, preds: list[dict[str, Any]]) -> dict:
    total = len(preds)
    value_plays = sum(1 for p in preds if p.get("edge") is not None and p["edge"] >= _VALUE_PLAY_THRESHOLD)
    leans = sum(1 for p in preds if p.get("edge") is not None and 0 < p["edge"] < _VALUE_PLAY_THRESHOLD)
    no_lines = sum(1 for p in preds if p.get("edge") is None)

    parts = [f"{total} games today"]
    if value_plays:
        parts.append(f"**{value_plays} value play{'s' if value_plays != 1 else ''}**")
    if leans:
        parts.append(f"{leans} lean{'s' if leans != 1 else ''}")
    if no_lines:
        parts.append(f"{no_lines} no lines yet")

    return {
        "title": f"NRFI Picks — {target_date}",
        "description": "  ·  ".join(parts),
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

        # Build pitcher name lookup: game_id → {away_sp_name, home_sp_name}
        pitcher_names: dict[int, dict[str, str | None]] = {}
        for game in games:
            gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
            if gp is not None:
                pitcher_names[game.id] = {
                    "away_sp_name": gp.away_sp.name if gp.away_sp else None,
                    "home_sp_name": gp.home_sp.name if gp.home_sp else None,
                }

        # Build first-inning odds lookup: game_id → {first_inn_over_odds, first_inn_under_odds}
        first_inn_odds: dict[int, dict[str, int | None]] = {}
        for game in games:
            odds_row = db.query(Odds).filter_by(game_id=game.id).first()
            if odds_row is not None:
                first_inn_odds[game.id] = {
                    "first_inn_over_odds": odds_row.first_inn_over_odds,
                    "first_inn_under_odds": odds_row.first_inn_under_odds,
                }

        preds = []
        for game in games:
            pred = predict_for_game(game.id, db)
            if pred is not None:
                pred.update(pitcher_names.get(game.id, {}))
                pred.update(first_inn_odds.get(game.id, {}))
                pred["game_time"] = game.game_time
                preds.append(pred)

        if not preds:
            logger.info("No predictions available for %s.", target)
            return

        logger.info("Posting %d predictions to Discord for %s.", len(preds), target)

        # Sort: highest edge first (None edge at the bottom)
        preds.sort(key=lambda p: (p["edge"] is None, -(p["edge"] or 0)))

        # Build all embeds: header + one per game
        header_embed = _build_header_embed(target, preds)
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
