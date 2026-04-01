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

# ESPN public CDN for MLB team logos (no API key required)
_ESPN_LOGO_BASE = "https://a.espncdn.com/i/teamlogos/mlb/500"
_TEAM_ESPN_SLUG: dict[str, str] = {
    "ARI": "ari", "ATL": "atl", "BAL": "bal", "BOS": "bos",
    "CHC": "chc", "CWS": "chw", "CIN": "cin", "CLE": "cle",
    "COL": "col", "DET": "det", "HOU": "hou", "KC":  "kc",
    "LAA": "laa", "LAD": "lad", "MIA": "mia", "MIL": "mil",
    "MIN": "min", "NYM": "nym", "NYY": "nyy", "ATH": "ath",
    "PHI": "phi", "PIT": "pit", "SD":  "sd",  "SEA": "sea",
    "SF":  "sf",  "STL": "stl", "TB":  "tb",  "TEX": "tex",
    "TOR": "tor", "WSH": "wsh",
}


def _team_logo_url(abbrev: str) -> str | None:
    slug = _TEAM_ESPN_SLUG.get(abbrev)
    return f"{_ESPN_LOGO_BASE}/{slug}.png" if slug else None

# Webhook payload limit: 10 embeds per request
_MAX_EMBEDS_PER_REQUEST = 10

# Edge threshold for a "strong" recommendation (same default as post_results.py)
_VALUE_PLAY_THRESHOLD = float(os.environ.get("VALUE_PLAY_THRESHOLD_PP", "2")) / 100.0


_EDGE_ZERO_THRESHOLD = 0.001  # treat |edge| < 0.1% as effectively zero (early-season anchor)


def _edge_color(edge: float | None, market: float | None = None) -> int:
    if edge is None:
        return _COLOR_GRAY
    if abs(edge) < _EDGE_ZERO_THRESHOLD:
        return _COLOR_GRAY
    if edge >= _VALUE_PLAY_THRESHOLD:
        return _COLOR_GREEN
    if edge > 0:
        return _COLOR_YELLOW
    if market is not None and market >= 0.60:
        return _COLOR_BLUE   # YRFI lean on heavy favorite
    return _COLOR_RED


def _recommendation(edge: float, model: float, market: float | None = None) -> str:
    """Concise read on whether to bet NRFI, lean, or fade."""
    edge_pct = f"{abs(edge) * 100:.0f}%"

    if abs(edge) < _EDGE_ZERO_THRESHOLD:
        return "⚪ **No model edge** — anchored to market (early-season, no in-season data yet)"
    elif edge >= _VALUE_PLAY_THRESHOLD:
        return f"🟢 **Model strongly favors NRFI** — {edge_pct} above market"
    elif edge > 0:
        return f"🟡 **Model leans NRFI** — slight disagreement with market"
    elif market is not None and market >= 0.60:
        edge_pct_mkt = f"{market * 100:.0f}%"
        return (
            f"🔵 **Lean YRFI** — market prices NRFI at {edge_pct_mkt} but historically "
            f"heavy favorites go NRFI only ~48–54%. Value may be on YRFI at these odds."
        )
    elif edge > -_VALUE_PLAY_THRESHOLD:
        return f"🟡 **Model leans YRFI** — market more confident in NRFI than model"
    else:
        return f"🔴 **Model strongly favors YRFI** — {edge_pct} below market"


def _fmt_odds(o: int | None) -> str:
    if o is None:
        return "N/A"
    return f"+{o}" if o > 0 else str(o)


_TZ_ET = ZoneInfo("America/New_York")
_TZ_CT = ZoneInfo("America/Chicago")
_TZ_PT = ZoneInfo("America/Los_Angeles")


def _fmt_game_time(game_time_utc: str | None) -> str | None:
    """Convert ISO UTC game time string to 'H:MM ET / H:MM CT / H:MM PT' format."""
    if not game_time_utc:
        return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(game_time_utc.replace("Z", "+00:00"))
        et = dt.astimezone(_TZ_ET).strftime("%-I:%M ET")
        ct = dt.astimezone(_TZ_CT).strftime("%-I:%M CT")
        pt = dt.astimezone(_TZ_PT).strftime("%-I:%M PT")
        return f"{et} / {ct} / {pt}"
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
        data_line = f"Model {model * 100:.1f}% · Mkt {market * 100:.1f}% · Edge {sign}{edge * 100:.1f}%"
        description = f"{pitchers_line}{odds_line}{data_line}\n{_recommendation(edge, model, market)}"
    elif model is not None:
        nrfi_pct = f"{model * 100:.0f}%"
        description = (
            f"{pitchers_line}{odds_line}Model {nrfi_pct} · Mkt N/A\n"
            f"⚪ No lines yet — model gives NRFI {nrfi_pct}"
        )
    else:
        description = "No prediction available."

    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": _edge_color(edge, market),
    }

    logo_url = _team_logo_url(home)
    if logo_url:
        embed["author"] = {"name": "MLB", "icon_url": logo_url}

    return embed


def _build_header_embed(target_date: str, preds: list[dict[str, Any]]) -> dict:
    total = len(preds)
    value_plays = sum(1 for p in preds if p.get("edge") is not None and p["edge"] >= _VALUE_PLAY_THRESHOLD)
    leans = sum(1 for p in preds if p.get("edge") is not None and _EDGE_ZERO_THRESHOLD <= p["edge"] < _VALUE_PLAY_THRESHOLD)
    anchored = sum(1 for p in preds if p.get("edge") is not None and abs(p["edge"]) < _EDGE_ZERO_THRESHOLD)
    shadow_yrfi = sum(
        1 for p in preds
        if p.get("p_nrfi_market") is not None and p["p_nrfi_market"] >= 0.60
    )
    no_lines = sum(1 for p in preds if p.get("edge") is None)

    parts = [f"{total} games today"]
    if value_plays:
        parts.append(f"**{value_plays} value play{'s' if value_plays != 1 else ''}**")
    if leans:
        parts.append(f"{leans} lean{'s' if leans != 1 else ''}")
    if anchored:
        parts.append(f"{anchored} anchored to market")
    if shadow_yrfi:
        parts.append(f"🔵 {shadow_yrfi} YRFI lean{'s' if shadow_yrfi != 1 else ''}")
    if no_lines:
        parts.append(f"{no_lines} no lines yet")

    description = "  ·  ".join(parts)

    # Early-season disclaimer — model lacks current-season rolling stats until ~April 15
    try:
        d = date.fromisoformat(target_date)
        if d.month < 4 or (d.month == 4 and d.day < 15):
            description += (
                "\n\n⚠️ **Early-season notice:** Predictions are based primarily on "
                "prior-season stats since most pitchers haven't accumulated enough 2026 "
                "starts yet for current-form data. Confidence will improve as the season progresses."
            )
    except Exception:
        pass

    return {
        "title": f"NRFI Picks — {target_date}",
        "description": description,
        "color": _COLOR_BLUE,
        "footer": {"text": "Model% = predicted probability of no run in the 1st inning. Mkt% = sportsbook implied probability. Edge = how much our model disagrees with the market."},
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
