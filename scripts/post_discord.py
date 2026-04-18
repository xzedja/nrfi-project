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

from sqlalchemy import extract

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


_EDGE_ZERO_THRESHOLD = 0.001        # treat |edge| < 0.1% as effectively zero (early-season anchor)
_HIGH_DISAGREEMENT_THRESHOLD = 0.07  # flag large model-market gaps as diagnostic
_ANTI_SIGNAL_THRESHOLD = 0.03        # edges ≥3% historically inverted (35% NRFI win rate in backtest)

# Before May 1, rolling within-season stats are too sparse — model picks are informational only
_ROLLING_STATS_CUTOFF = (5, 1)       # (month, day)


def _is_early_season(target_date_str: str) -> bool:
    """Return True if rolling stats are not yet populated (before May 1)."""
    try:
        d = date.fromisoformat(target_date_str)
        return d < date(d.year, *_ROLLING_STATS_CUTOFF)
    except Exception:
        return False


def _edge_color(edge: float | None, market: float | None = None, target_date: str | None = None) -> int:
    if edge is None:
        return _COLOR_GRAY
    if abs(edge) < _EDGE_ZERO_THRESHOLD:
        return _COLOR_GRAY
    # YRFI signal always blue regardless of model edge or season
    if market is not None and market >= 0.60:
        return _COLOR_BLUE
    # Early season: all model picks are gray (informational only)
    if target_date and _is_early_season(target_date):
        return _COLOR_GRAY
    # Anti-signal: 3%+ model edges are historically inverted — show yellow, not green
    if edge >= _ANTI_SIGNAL_THRESHOLD:
        return _COLOR_YELLOW
    if edge >= _VALUE_PLAY_THRESHOLD:
        return _COLOR_YELLOW
    if edge > 0:
        return _COLOR_YELLOW
    return _COLOR_RED


def _recommendation(edge: float, model: float, market: float | None = None, target_date: str | None = None) -> str:
    """Concise read on the model lean. Model picks are experimental; YRFI signal is market-driven."""
    edge_pct = f"{abs(edge) * 100:.0f}%"

    if abs(edge) < _EDGE_ZERO_THRESHOLD:
        return "⚪ **No model edge** — anchored to market (rolling stats not yet populated)"

    # YRFI signal: always active, always confident framing
    if market is not None and market >= 0.60:
        edge_pct_mkt = f"{market * 100:.0f}%"
        return (
            f"🔵 **YRFI signal** — market prices NRFI at {edge_pct_mkt} but historically "
            f"heavy favorites go NRFI only ~48–54%. +46–54% ROI over 2,700 bets (2023–24)."
        )

    # Early season: model picks are informational only — no actionable language
    if target_date and _is_early_season(target_date):
        sign = "+" if edge >= 0 else ""
        direction = "above" if edge >= 0 else "below"
        return (
            f"⚪ **Informational** — model is {sign}{edge * 100:.1f}% {direction} market. "
            f"Rolling stats not yet populated; model picks resume May 1."
        )

    # Anti-signal: backtest shows ≥3% positive edge wins only 35–46% of the time
    if edge >= _ANTI_SIGNAL_THRESHOLD:
        return (
            f"⚠️ **Large model-market gap ({edge_pct} above market)** — "
            f"historically these games go YRFI more often than NRFI. Not a betting signal."
        )

    if edge >= _VALUE_PLAY_THRESHOLD:
        return "🟡 **Model leans NRFI** — slight edge over market (1–3% range, marginal ROI)"
    if edge > 0:
        return "🟡 **Model leans NRFI** — slight disagreement with market"
    if edge > -_VALUE_PLAY_THRESHOLD:
        return "🟡 **Model leans YRFI** — market more confident in NRFI than model"

    diagnostic_note = (
        "\n*(Gap this large is often a model data issue — treat as diagnostic, not a bet)*"
        if abs(edge) >= _HIGH_DISAGREEMENT_THRESHOLD else ""
    )
    return f"🔴 **Model leans YRFI** — {edge_pct} below market{diagnostic_note}"


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


def _load_pitcher_nrfi_records(
    db, pitcher_db_ids: list[int], seasons: list[int]
) -> dict[int, dict[int, str]]:
    """
    Return {pitcher_db_id: {year: "holds/starts"}} for the given seasons.

    For each game in the requested seasons where the pitcher was the home SP
    or away SP, counts:
      - Home SP holds: inning_1_away_runs == 0
      - Away SP holds: inning_1_home_runs == 0
    Combined into a single record regardless of home/away role.
    """
    if not pitcher_db_ids or not seasons:
        return {}

    result: dict[int, dict[int, str]] = {pid: {} for pid in pitcher_db_ids}

    for season in seasons:
        rows = (
            db.query(
                Game.inning_1_home_runs,
                Game.inning_1_away_runs,
                GamePitchers.home_sp_id,
                GamePitchers.away_sp_id,
            )
            .join(GamePitchers, Game.id == GamePitchers.game_id)
            .filter(
                extract("year", Game.game_date) == season,
                Game.inning_1_home_runs.isnot(None),
                Game.inning_1_away_runs.isnot(None),
            )
            .all()
        )

        # {pitcher_db_id: [holds, starts]}
        counts: dict[int, list[int]] = {pid: [0, 0] for pid in pitcher_db_ids}

        for h_runs, a_runs, home_sp_id, away_sp_id in rows:
            if home_sp_id in counts:
                counts[home_sp_id][1] += 1
                if a_runs == 0:
                    counts[home_sp_id][0] += 1
            if away_sp_id in counts:
                counts[away_sp_id][1] += 1
                if h_runs == 0:
                    counts[away_sp_id][0] += 1

        for pid, (h, s) in counts.items():
            if s > 0:
                result[pid][season] = f"{h}/{s}"

    return result


def _fmt_pitcher_record(records: dict[int, str]) -> str:
    """Format {year: 'holds/starts'} as ''25: 14/22 (64%) · '26: 3/5 (60%)'."""
    if not records:
        return ""
    parts = []
    for year in sorted(records):
        record = records[year]
        try:
            h, s = record.split("/")
            pct = f"{int(h) / int(s) * 100:.0f}%"
            parts.append(f"'{str(year)[-2:]}: {record} ({pct})")
        except Exception:
            parts.append(f"'{str(year)[-2:]}: {record}")
    return " · ".join(parts)


def _build_game_embed(pred: dict[str, Any]) -> dict:
    """Build a single Discord embed dict for one game prediction."""
    away = pred["away_team"]
    home = pred["home_team"]
    edge = pred.get("edge")
    model = pred.get("p_nrfi_model")
    market = pred.get("p_nrfi_market")
    away_sp = pred.get("away_sp_name")
    home_sp = pred.get("home_sp_name")
    away_sp_record = _fmt_pitcher_record(pred.get("away_sp_nrfi_records", {}))
    home_sp_record = _fmt_pitcher_record(pred.get("home_sp_nrfi_records", {}))
    nrfi_odds = pred.get("first_inn_under_odds")
    yrfi_odds = pred.get("first_inn_over_odds")
    game_time_str = _fmt_game_time(pred.get("game_time"))

    title = f"{away} @ {home}"
    if game_time_str:
        title += f"  ·  {game_time_str}"

    pitchers_line = f"{away_sp} vs {home_sp}\n" if away_sp and home_sp else ""
    records_parts = []
    if away_sp_record:
        records_parts.append(f"Away: {away_sp_record}")
    if home_sp_record:
        records_parts.append(f"Home: {home_sp_record}")
    records_line = f"Scoreless 1st inns — {' | '.join(records_parts)}\n" if records_parts else ""

    if nrfi_odds is not None or yrfi_odds is not None:
        odds_line = f"NRFI {_fmt_odds(nrfi_odds)} · YRFI {_fmt_odds(yrfi_odds)}\n"
    else:
        odds_line = ""

    target_date = pred.get("game_date")

    if model is not None and market is not None and edge is not None:
        sign = "+" if edge >= 0 else ""
        data_line = f"Model {model * 100:.1f}% · Mkt {market * 100:.1f}% · Edge {sign}{edge * 100:.1f}%"
        description = f"{pitchers_line}{records_line}{odds_line}{data_line}\n{_recommendation(edge, model, market, target_date)}"
    elif model is not None:
        nrfi_pct = f"{model * 100:.0f}%"
        description = (
            f"{pitchers_line}{records_line}{odds_line}Model {nrfi_pct} · Mkt N/A\n"
            f"⚪ No lines yet — model gives NRFI {nrfi_pct}"
        )
    else:
        description = "No prediction available."

    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": _edge_color(edge, market, target_date),
    }

    logo_url = _team_logo_url(home)
    if logo_url:
        embed["author"] = {"name": "MLB", "icon_url": logo_url}

    return embed


def _build_header_embed(target_date: str, preds: list[dict[str, Any]]) -> dict:
    total = len(preds)
    early = _is_early_season(target_date)

    yrfi_signals = sum(
        1 for p in preds
        if p.get("p_nrfi_market") is not None and p["p_nrfi_market"] >= 0.60
    )
    model_leans = sum(
        1 for p in preds
        if p.get("edge") is not None
        and _EDGE_ZERO_THRESHOLD <= p["edge"] < _ANTI_SIGNAL_THRESHOLD
        and not early
    )
    anti_signals = sum(
        1 for p in preds
        if p.get("edge") is not None and p["edge"] >= _ANTI_SIGNAL_THRESHOLD
    )
    no_lines = sum(1 for p in preds if p.get("edge") is None)

    parts = [f"{total} games today"]
    if yrfi_signals:
        parts.append(f"🔵 {yrfi_signals} YRFI signal{'s' if yrfi_signals != 1 else ''}")
    if model_leans:
        parts.append(f"{model_leans} model lean{'s' if model_leans != 1 else ''} (1–3%)")
    if anti_signals and not early:
        parts.append(f"{anti_signals} diagnostic gap{'s' if anti_signals != 1 else ''}")
    if no_lines:
        parts.append(f"{no_lines} no lines yet")

    description = "  ·  ".join(parts)

    if early:
        description += (
            "\n\n⚠️ **Early-season (model picks muted until May 1):** Rolling within-season "
            "pitcher stats are not yet populated. Model picks shown as informational only. "
            "🔵 YRFI signals are market-based (+46–54% ROI historically) and remain active."
        )

    return {
        "title": f"NRFI Picks — {target_date}",
        "description": description,
        "color": _COLOR_BLUE,
        "footer": {"text": "Model% = predicted NRFI probability. Mkt% = sportsbook implied probability. Edge = model vs market gap. 🔵 YRFI signals are market-driven (+46–54% ROI historically). Model leans active after May 1."},
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

        # Build pitcher name + DB ID lookup: game_id → {away_sp_name, home_sp_name, *_db_id}
        pitcher_names: dict[int, dict[str, str | int | None]] = {}
        all_pitcher_db_ids: set[int] = set()
        for game in games:
            gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
            if gp is not None:
                home_db_id = gp.home_sp_id
                away_db_id = gp.away_sp_id
                pitcher_names[game.id] = {
                    "away_sp_name": gp.away_sp.name if gp.away_sp else None,
                    "home_sp_name": gp.home_sp.name if gp.home_sp else None,
                    "away_sp_db_id": away_db_id,
                    "home_sp_db_id": home_db_id,
                }
                if home_db_id:
                    all_pitcher_db_ids.add(home_db_id)
                if away_db_id:
                    all_pitcher_db_ids.add(away_db_id)

        # Load pitcher NRFI records for 2025 and current season
        current_year = date.fromisoformat(target).year
        record_seasons = sorted({2025, current_year})
        pitcher_nrfi_records = _load_pitcher_nrfi_records(
            db, list(all_pitcher_db_ids), record_seasons
        )

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
                names = pitcher_names.get(game.id, {})
                pred.update(names)
                pred.update(first_inn_odds.get(game.id, {}))
                pred["game_time"] = game.game_time
                # Attach per-pitcher NRFI records for display
                home_db_id = names.get("home_sp_db_id")
                away_db_id = names.get("away_sp_db_id")
                pred["home_sp_nrfi_records"] = pitcher_nrfi_records.get(home_db_id, {}) if home_db_id else {}
                pred["away_sp_nrfi_records"] = pitcher_nrfi_records.get(away_db_id, {}) if away_db_id else {}
                preds.append(pred)

        if not preds:
            logger.info("No predictions available for %s.", target)
            return

        logger.info("Posting %d predictions to Discord for %s.", len(preds), target)

        # Sort: by signal tier, then by game time within each tier
        def _tier(p: dict) -> int:
            edge = p.get("edge")
            market = p.get("p_nrfi_market")
            # YRFI signal always first — confirmed edge
            if market is not None and market >= 0.60:
                return 0
            if edge is None or abs(edge) < _EDGE_ZERO_THRESHOLD:
                return 5  # no lines / anchored
            if _VALUE_PLAY_THRESHOLD <= edge < _ANTI_SIGNAL_THRESHOLD:
                return 1  # model lean NRFI 1–3% (marginal positive ROI)
            if edge > 0 and edge < _VALUE_PLAY_THRESHOLD:
                return 2  # slight NRFI lean <1%
            if edge >= _ANTI_SIGNAL_THRESHOLD:
                return 4  # anti-signal — diagnostic, not actionable
            if edge > -_VALUE_PLAY_THRESHOLD:
                return 3  # slight YRFI lean
            return 4      # red — model leans YRFI / anti-signal

        preds.sort(key=lambda p: (_tier(p), p.get("game_time") or "9999"))

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
