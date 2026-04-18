"""
scripts/discord_bot.py

Discord gateway bot for NRFI slash commands.

Connects outbound to Discord — works behind CGNAT with no public URL required.

Commands:
  /display-picks   — ephemeral embed showing today's full picks (only visible to requester)
  /today-record    — public embed showing today's picks W/L record
  /tomorrow-picks  — ephemeral embed showing tomorrow's picks
  /yrfi-signals    — ephemeral embed showing today's YRFI signal games (market 60%+ NRFI)
  /season-record   — ephemeral embed showing season W/L for model picks + YRFI signal
  /refresh-odds    — triggers odds refresh pipeline for today (ephemeral)
  /yesterday-picks  — ephemeral embed showing yesterday's results
  /pitcher-stats    — ephemeral embed showing today's starters: prior-season ERA/FIP/WHIP/K%/BB%, current-season last-5 ERA/WHIP/1st-inn ERA, days rest, and 1st-inn hold record

Usage:
    DATABASE_URL=... DISCORD_BOT_TOKEN=... python scripts/discord_bot.py

Environment vars:
  DISCORD_BOT_TOKEN  — required, from Discord Developer Portal → Bot
  DISCORD_GUILD_ID   — optional, syncs commands instantly to one server (omit for global)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import date
from typing import Any

import discord
from discord import app_commands

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.db.models import Game, GamePitchers, NrfiFeatures, Odds, Pitcher
from backend.db.session import SessionLocal
from backend.data.fetch_odds import american_to_implied, remove_vig
from backend.modeling.predict import predict_for_game
from scripts.backfill_game_results import _fetch_linescore_map as _fetch_final_linescore_map

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GUILD_ID   = os.environ.get("DISCORD_GUILD_ID", "")

if not BOT_TOKEN:
    logger.error("DISCORD_BOT_TOKEN not set — exiting.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Embed helpers (mirrors post_discord.py)
# ---------------------------------------------------------------------------

_COLOR_GREEN  = 0x2ECC71
_COLOR_YELLOW = 0xF1C40F
_COLOR_RED    = 0xE74C3C
_COLOR_GRAY   = 0x95A5A6
_COLOR_BLUE   = 0x3498DB

_VALUE_PLAY_THRESHOLD  = float(os.environ.get("VALUE_PLAY_THRESHOLD_PP", "2")) / 100.0
_EDGE_ZERO_THRESHOLD   = 0.001
_YRFI_SIGNAL_THRESHOLD = 0.60

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

try:
    from zoneinfo import ZoneInfo
    _TZ_ET = ZoneInfo("America/New_York")
    _TZ_CT = ZoneInfo("America/Chicago")
    _TZ_PT = ZoneInfo("America/Los_Angeles")
except Exception:
    _TZ_ET = _TZ_CT = _TZ_PT = None


def _team_logo_url(abbrev: str) -> str | None:
    slug = _TEAM_ESPN_SLUG.get(abbrev)
    return f"{_ESPN_LOGO_BASE}/{slug}.png" if slug else None


def _fmt_odds(o: int | None) -> str:
    if o is None:
        return "N/A"
    return f"+{o}" if o > 0 else str(o)


def _fmt_game_time(game_time_utc: str | None) -> str | None:
    if not game_time_utc or _TZ_ET is None:
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


def _edge_color(edge: float | None, market: float | None = None) -> int:
    if edge is None:
        return _COLOR_GRAY
    if abs(edge) < _EDGE_ZERO_THRESHOLD:
        return _COLOR_GRAY
    if edge >= _VALUE_PLAY_THRESHOLD:
        return _COLOR_GREEN
    if edge > 0:
        return _COLOR_YELLOW
    if market is not None and market >= _YRFI_SIGNAL_THRESHOLD:
        return _COLOR_BLUE
    return _COLOR_RED


def _recommendation(edge: float, market: float | None = None) -> str:
    edge_pct = f"{abs(edge) * 100:.0f}%"
    if abs(edge) < _EDGE_ZERO_THRESHOLD:
        return "⚪ **No model edge** — anchored to market (early-season, no in-season data yet)"
    elif edge >= _VALUE_PLAY_THRESHOLD:
        return f"🟢 **Model strongly favors NRFI** — {edge_pct} above market"
    elif edge > 0:
        return f"🟡 **Model leans NRFI** — slight disagreement with market"
    elif market is not None and market >= _YRFI_SIGNAL_THRESHOLD:
        mkt_pct = f"{market * 100:.0f}%"
        return (
            f"🔵 **Lean YRFI** — market prices NRFI at {mkt_pct} but historically "
            f"heavy favorites go NRFI only ~48–54%. Value may be on YRFI at these odds."
        )
    elif edge > -_VALUE_PLAY_THRESHOLD:
        return f"🟡 **Model leans YRFI** — market more confident in NRFI than model"
    else:
        return f"🔴 **Model strongly favors YRFI** — {edge_pct} below market"


def _build_pick_embed(pred: dict[str, Any]) -> dict:
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
    odds_line = (
        f"NRFI {_fmt_odds(nrfi_odds)} · YRFI {_fmt_odds(yrfi_odds)}\n"
        if nrfi_odds is not None or yrfi_odds is not None else ""
    )

    if model is not None and market is not None and edge is not None:
        sign = "+" if edge >= 0 else ""
        data_line = f"Model {model * 100:.1f}% · Mkt {market * 100:.1f}% · Edge {sign}{edge * 100:.1f}%"
        description = f"{pitchers_line}{odds_line}{data_line}\n{_recommendation(edge, market)}"
    elif model is not None:
        nrfi_pct = f"{model * 100:.0f}%"
        description = f"{pitchers_line}{odds_line}Model {nrfi_pct} · Mkt N/A\n⚪ No lines yet — model gives NRFI {nrfi_pct}"
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


def _fetch_first_inning_live(date_str: str) -> dict[int, dict]:
    """
    Fetch first-inning run totals for all games on date_str regardless of
    game state (in-progress, final, etc.). Returns {game_pk: {"home": int, "away": int}}
    only for games where inning 1 data exists.
    """
    import requests
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={date_str}&hydrate=linescore"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    result: dict[int, dict] = {}
    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            game_pk = game.get("gamePk")
            innings = game.get("linescore", {}).get("innings", [])
            if not innings:
                continue
            first_inn = innings[0]
            home_runs = first_inn.get("home", {}).get("runs")
            away_runs = first_inn.get("away", {}).get("runs")
            if home_runs is not None and away_runs is not None:
                result[int(game_pk)] = {"home": int(home_runs), "away": int(away_runs)}
    return result


def _build_record_embed(target_date: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        games = db.query(Game).filter(Game.game_date == target_date).all()

        # Always fetch live first-inning data — works for in-progress and final games
        live_scores = _fetch_first_inning_live(target_date)

        picks = []
        for game in games:
            feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()
            if feat is None or feat.p_nrfi_model is None:
                continue

            p_market = feat.p_nrfi_market
            if p_market is None:
                odds_row = db.query(Odds).filter_by(game_id=game.id).first()
                if odds_row and odds_row.first_inn_under_odds and odds_row.first_inn_over_odds:
                    p_yrfi_raw = american_to_implied(odds_row.first_inn_over_odds)
                    p_nrfi_raw = american_to_implied(odds_row.first_inn_under_odds)
                    _, p_market = remove_vig(p_yrfi_raw, p_nrfi_raw)
                    p_market = round(p_market, 4)

            if p_market is None:
                continue

            edge = feat.p_nrfi_model - p_market
            if edge <= 0:
                continue

            gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
            away_sp = gp.away_sp.name if gp and gp.away_sp else None
            home_sp = gp.home_sp.name if gp and gp.home_sp else None

            odds_row = db.query(Odds).filter_by(game_id=game.id).first()
            nrfi_odds = odds_row.first_inn_under_odds if odds_row else None
            yrfi_odds = odds_row.first_inn_over_odds if odds_row else None

            # DB result takes priority; fall back to live first-inning data
            if game.nrfi is not None:
                outcome = game.nrfi
            elif game.external_id and game.external_id in live_scores:
                s = live_scores[game.external_id]
                outcome = (s["home"] == 0) and (s["away"] == 0)
            else:
                outcome = None  # not yet started

            picks.append({
                "matchup": f"{game.away_team} @ {game.home_team}",
                "pitchers": f"{away_sp} vs {home_sp}" if away_sp and home_sp else None,
                "edge": edge,
                "outcome": outcome,
                "p_model": feat.p_nrfi_model,
                "p_market": p_market,
                "nrfi_odds": nrfi_odds,
                "yrfi_odds": yrfi_odds,
            })

        if not picks:
            return {
                "title": f"Today's Record — {target_date}",
                "description": "No positive-edge picks found for today.",
                "color": _COLOR_GRAY,
            }

        wins    = sum(1 for p in picks if p["outcome"] is True)
        losses  = sum(1 for p in picks if p["outcome"] is False)
        pending = sum(1 for p in picks if p["outcome"] is None)

        record_parts = []
        if wins or losses:
            record_parts.append(f"**{wins}W - {losses}L**")
        if pending:
            record_parts.append(f"{pending} pending")
        record_str = "  ·  ".join(record_parts) if record_parts else "All pending"

        lines = []
        for p in picks:
            icon = "✅" if p["outcome"] is True else ("❌" if p["outcome"] is False else "⏳")
            sign = "+" if p["edge"] >= 0 else ""
            data_line = (
                f"Model {p['p_model'] * 100:.1f}% · "
                f"Mkt {p['p_market'] * 100:.1f}% · "
                f"Edge {sign}{p['edge'] * 100:.1f}%"
            )
            odds_line = ""
            if p["nrfi_odds"] is not None or p["yrfi_odds"] is not None:
                odds_line = f"\n   NRFI {_fmt_odds(p['nrfi_odds'])} · YRFI {_fmt_odds(p['yrfi_odds'])}"

            line = f"{icon} **{p['matchup']}**{odds_line}\n   {data_line}"
            if p["pitchers"]:
                line += f"\n   ↳ {p['pitchers']}"
            lines.append(line)

        color = _COLOR_GREEN if wins > losses else (_COLOR_YELLOW if wins == losses and (wins or losses) else _COLOR_GRAY)

        return {
            "title": f"NRFI Picks — {target_date}",
            "description": f"{record_str}\n\n" + "\n\n".join(lines),
            "color": color,
            "footer": {"text": "Model% = predicted probability of no run in the 1st inning. Mkt% = sportsbook implied probability. Edge = how much our model disagrees with the market."},
        }
    finally:
        db.close()


def _build_picks_embeds(target_date: str) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        games = db.query(Game).filter(Game.game_date == target_date).all()
        if not games:
            return [{"title": f"NRFI Picks — {target_date}", "description": "No games found for today.", "color": _COLOR_GRAY}]

        preds = []
        for game in games:
            pred = predict_for_game(game.id, db)
            if pred is None:
                continue

            gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
            if gp:
                pred["away_sp_name"] = gp.away_sp.name if gp.away_sp else None
                pred["home_sp_name"] = gp.home_sp.name if gp.home_sp else None

            odds_row = db.query(Odds).filter_by(game_id=game.id).first()
            if odds_row:
                pred["first_inn_over_odds"]  = odds_row.first_inn_over_odds
                pred["first_inn_under_odds"] = odds_row.first_inn_under_odds

            pred["game_time"] = game.game_time
            preds.append(pred)

        if not preds:
            return [{"title": f"NRFI Picks — {target_date}", "description": "No predictions available yet.", "color": _COLOR_GRAY}]

        preds.sort(key=lambda p: (p["edge"] is None, -(p["edge"] or 0)))

        value_plays  = sum(1 for p in preds if p.get("edge") is not None and p["edge"] >= _VALUE_PLAY_THRESHOLD)
        leans        = sum(1 for p in preds if p.get("edge") is not None and 0 < p["edge"] < _VALUE_PLAY_THRESHOLD)
        yrfi_signals = sum(1 for p in preds if p.get("p_nrfi_market") is not None and p["p_nrfi_market"] >= _YRFI_SIGNAL_THRESHOLD)
        no_lines     = sum(1 for p in preds if p.get("edge") is None)

        parts = [f"{len(preds)} games today"]
        if value_plays:
            parts.append(f"**{value_plays} value play{'s' if value_plays != 1 else ''}**")
        if leans:
            parts.append(f"{leans} lean{'s' if leans != 1 else ''}")
        if yrfi_signals:
            parts.append(f"🔵 {yrfi_signals} YRFI signal{'s' if yrfi_signals != 1 else ''}")
        if no_lines:
            parts.append(f"{no_lines} no lines yet")

        description = "  ·  ".join(parts)

        try:
            from datetime import date as _date
            d = _date.fromisoformat(target_date)
            if d.month < 4 or (d.month == 4 and d.day < 15):
                description += (
                    "\n\n⚠️ **Early-season notice:** Predictions are based primarily on "
                    "prior-season stats since most pitchers haven't accumulated enough 2026 "
                    "starts yet for current-form data. Confidence will improve as the season progresses."
                )
        except Exception:
            pass

        header = {
            "title": f"NRFI Picks — {target_date}",
            "description": description,
            "color": _COLOR_BLUE,
            "footer": {"text": "Model% = predicted probability of no run in the 1st inning. Mkt% = sportsbook implied probability. Edge = how much our model disagrees with the market."},
        }

        game_embeds = [_build_pick_embed(p) for p in preds]
        return [header] + game_embeds

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class NRFIBot(discord.Client):
    def __init__(self, guild_id: int | None = None):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._guild_id = guild_id

    async def setup_hook(self) -> None:
        if self._guild_id:
            guild = discord.Object(id=self._guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Slash commands synced to guild %s (instant).", self._guild_id)
        else:
            await self.tree.sync()
            logger.info("Slash commands synced globally (may take up to 1 hour).")

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id)


guild_id = int(GUILD_ID) if GUILD_ID else None
bot = NRFIBot(guild_id=guild_id)


@bot.tree.command(name="today-record", description="Show today's NRFI picks and current W/L record.")
async def today_record(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    target_date = str(date.today())
    embed_data = await asyncio.get_event_loop().run_in_executor(
        None, _build_record_embed, target_date
    )
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="display-picks", description="Show today's NRFI picks privately (only you can see).")
async def display_picks(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    target_date = str(date.today())
    embeds_data = await asyncio.get_event_loop().run_in_executor(
        None, _build_picks_embeds, target_date
    )
    embeds = [discord.Embed.from_dict(e) for e in embeds_data]

    # Send in batches of 10 (Discord limit per message)
    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i + 10]
        await interaction.followup.send(embeds=chunk, ephemeral=True)


def _build_yrfi_signals_embed(target_date: str) -> dict[str, Any]:
    """Build embed showing only YRFI signal games (market >= 60% NRFI)."""
    db = SessionLocal()
    try:
        games = db.query(Game).filter(Game.game_date == target_date).all()
        signals = []
        for game in games:
            pred = predict_for_game(game.id, db)
            if pred is None:
                continue
            market = pred.get("p_nrfi_market")
            if market is None or market < _YRFI_SIGNAL_THRESHOLD:
                continue

            gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
            away_sp = gp.away_sp.name if gp and gp.away_sp else None
            home_sp = gp.home_sp.name if gp and gp.home_sp else None

            odds_row = db.query(Odds).filter_by(game_id=game.id).first()
            nrfi_odds = odds_row.first_inn_under_odds if odds_row else None
            yrfi_odds = odds_row.first_inn_over_odds if odds_row else None

            game_time_str = _fmt_game_time(game.game_time)
            title = f"{game.away_team} @ {game.home_team}"
            if game_time_str:
                title += f"  ·  {game_time_str}"

            pitchers = f"{away_sp} vs {home_sp}" if away_sp and home_sp else ""
            odds_str = f"NRFI {_fmt_odds(nrfi_odds)} · YRFI {_fmt_odds(yrfi_odds)}" if nrfi_odds or yrfi_odds else ""
            edge = pred.get("edge")
            sign = "+" if edge is not None and edge >= 0 else ""
            edge_str = f"{sign}{edge * 100:.1f}%" if edge is not None else "N/A"

            signals.append(
                f"**{title}**"
                + (f"\n{pitchers}" if pitchers else "")
                + (f"\n{odds_str}" if odds_str else "")
                + f"\nMkt {market * 100:.1f}% NRFI · Edge {edge_str}"
            )

        if not signals:
            return {
                "title": f"🔵 YRFI Signals — {target_date}",
                "description": "No games with market ≥ 60% NRFI today.",
                "color": _COLOR_GRAY,
            }

        return {
            "title": f"🔵 YRFI Signals — {target_date}",
            "description": (
                f"{len(signals)} game{'s' if len(signals) != 1 else ''} with market ≥ 60% NRFI "
                f"— bet YRFI on these\n\n"
                + "\n\n".join(signals)
            ),
            "color": _COLOR_BLUE,
            "footer": {"text": "Historical ROI: +46–54% when market implies ≥60% NRFI. Bet YRFI at the posted over line."},
        }
    finally:
        db.close()


def _build_season_record_embed() -> dict[str, Any]:
    """Build embed showing season W/L for model picks and YRFI signal."""
    from backend.data.fetch_odds import american_to_implied, remove_vig

    _value_threshold = _VALUE_PLAY_THRESHOLD
    _yrfi_threshold  = _YRFI_SIGNAL_THRESHOLD

    db = SessionLocal()
    try:
        season_rows = (
            db.query(Game, NrfiFeatures)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(
                NrfiFeatures.nrfi_label.isnot(None),
                NrfiFeatures.p_nrfi_model.isnot(None),
            )
            .all()
        )

        all_w = all_l = val_w = val_l = yrfi_w = yrfi_l = 0

        for game, feat in season_rows:
            p_market = feat.p_nrfi_market
            if p_market is None:
                odds_row = db.query(Odds).filter_by(game_id=feat.game_id).first()
                if odds_row and odds_row.first_inn_under_odds and odds_row.first_inn_over_odds:
                    p_yrfi_raw = american_to_implied(odds_row.first_inn_over_odds)
                    p_nrfi_raw = american_to_implied(odds_row.first_inn_under_odds)
                    _, p_market = remove_vig(p_yrfi_raw, p_nrfi_raw)
            if p_market is None:
                continue

            edge = feat.p_nrfi_model - p_market
            won_nrfi = bool(feat.nrfi_label)
            won_yrfi = not won_nrfi

            if edge > 0:
                all_w += int(won_nrfi)
                all_l += int(not won_nrfi)
                if edge >= _value_threshold:
                    val_w += int(won_nrfi)
                    val_l += int(not won_nrfi)

            if p_market >= _yrfi_threshold:
                yrfi_w += int(won_yrfi)
                yrfi_l += int(not won_yrfi)

        def _wl(w, l):
            total = w + l
            pct = f"{w / total * 100:.1f}%" if total else "—"
            return f"{w}-{l} ({pct})" if total else "No bets yet"

        year = date.today().year
        return {
            "title": f"📊 Season Record — {year}",
            "color": _COLOR_BLUE,
            "fields": [
                {"name": "All Model Picks (edge > 0)", "value": _wl(all_w, all_l), "inline": True},
                {"name": f"Value Plays (edge > +{int(_value_threshold * 100)}%)", "value": _wl(val_w, val_l), "inline": True},
                {"name": f"🔵 YRFI Signal (market ≥ {int(_yrfi_threshold * 100)}% NRFI)", "value": _wl(yrfi_w, yrfi_l), "inline": False},
            ],
            "footer": {"text": "YRFI Signal: bet YRFI when market implies ≥60% NRFI. Historical ROI +46–54%."},
        }
    finally:
        db.close()


def _build_yesterday_embed() -> dict[str, Any]:
    """Build embed showing yesterday's results for model picks and YRFI signal."""
    from datetime import timedelta
    score_date = str(date.today() - timedelta(days=1))

    db = SessionLocal()
    try:
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
            return {
                "title": f"Yesterday's Results — {score_date}",
                "description": "No completed results found.",
                "color": _COLOR_GRAY,
            }

        nrfi_lines = []
        yrfi_lines = []
        nrfi_w = nrfi_l = yrfi_w = yrfi_l = 0

        for game, feat in rows:
            p_market = feat.p_nrfi_market
            if p_market is None:
                odds_row = db.query(Odds).filter_by(game_id=feat.game_id).first()
                if odds_row and odds_row.first_inn_under_odds and odds_row.first_inn_over_odds:
                    p_yrfi_raw = american_to_implied(odds_row.first_inn_over_odds)
                    p_nrfi_raw = american_to_implied(odds_row.first_inn_under_odds)
                    _, p_market = remove_vig(p_yrfi_raw, p_nrfi_raw)
            if p_market is None:
                continue

            edge = feat.p_nrfi_model - p_market
            actual_nrfi = bool(feat.nrfi_label)

            if edge > 0:
                won = actual_nrfi
                icon = "✅" if won else "❌"
                outcome = "NRFI ✓" if actual_nrfi else "YRFI"
                sign = "+" if edge >= 0 else ""
                nrfi_lines.append(
                    f"{icon} {game.away_team} @ {game.home_team} — {outcome} | "
                    f"Model {feat.p_nrfi_model * 100:.0f}% · Mkt {p_market * 100:.0f}% · Edge {sign}{edge * 100:.0f}%"
                )
                nrfi_w += int(won)
                nrfi_l += int(not won)

            if p_market >= _YRFI_SIGNAL_THRESHOLD:
                won_yrfi = not actual_nrfi
                icon = "✅" if won_yrfi else "❌"
                outcome = "YRFI ✓" if not actual_nrfi else "NRFI"
                yrfi_lines.append(
                    f"{icon} {game.away_team} @ {game.home_team} — {outcome} | Mkt {p_market * 100:.0f}% NRFI"
                )
                yrfi_w += int(won_yrfi)
                yrfi_l += int(not won_yrfi)

        def _wl(w, l):
            total = w + l
            pct = f"{w / total * 100:.1f}%" if total else "—"
            return f"{w}-{l} ({pct})"

        parts = []
        if nrfi_lines:
            parts.append(f"**Model Picks — {_wl(nrfi_w, nrfi_l)}**\n" + "\n".join(nrfi_lines))
        else:
            parts.append("**Model Picks** — No positive-edge picks yesterday.")

        if yrfi_lines:
            parts.append(f"**🔵 YRFI Signal — {_wl(yrfi_w, yrfi_l)}**\n" + "\n".join(yrfi_lines))

        color = _COLOR_GREEN if (nrfi_w + yrfi_w) > (nrfi_l + yrfi_l) else _COLOR_RED

        return {
            "title": f"Yesterday's Results — {score_date}",
            "description": "\n\n".join(parts),
            "color": color,
        }
    finally:
        db.close()


def _load_pitcher_hold_records(
    db, pitcher_db_ids: list[int], seasons: list[int]
) -> dict[int, dict[int, str]]:
    """Return {pitcher_db_id: {year: 'holds/starts'}} for each season."""
    if not pitcher_db_ids or not seasons:
        return {}

    from sqlalchemy import extract as _extract

    result: dict[int, dict[int, str]] = {pid: {} for pid in pitcher_db_ids}
    id_set = set(pitcher_db_ids)

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
                _extract("year", Game.game_date) == season,
                Game.inning_1_home_runs.isnot(None),
                Game.inning_1_away_runs.isnot(None),
            )
            .all()
        )

        counts: dict[int, list[int]] = {pid: [0, 0] for pid in pitcher_db_ids}
        for h_runs, a_runs, home_sp_id, away_sp_id in rows:
            if home_sp_id in id_set and home_sp_id in counts:
                counts[home_sp_id][1] += 1
                if a_runs == 0:
                    counts[home_sp_id][0] += 1
            if away_sp_id in id_set and away_sp_id in counts:
                counts[away_sp_id][1] += 1
                if h_runs == 0:
                    counts[away_sp_id][0] += 1

        for pid, (h, s) in counts.items():
            if s > 0:
                result[pid][season] = f"{h}/{s}"

    return result


def _fmt_sp_stats(prefix: str, feat: Any | None, hold_records: dict[int, str]) -> str:
    """
    Format one starter's stats as an embed field value.
    prefix: 'home_sp' or 'away_sp'
    hold_records: {year: 'holds/starts'} for this pitcher
    """
    lines = []

    if feat is not None:
        # Prior-season Fangraphs stats
        era_val    = getattr(feat, f"{prefix}_era",    None)
        fip_val    = getattr(feat, f"{prefix}_fip",    None)
        whip_val   = getattr(feat, f"{prefix}_whip",   None)
        k_pct_val  = getattr(feat, f"{prefix}_k_pct",  None)
        bb_pct_val = getattr(feat, f"{prefix}_bb_pct", None)

        prior_parts = []
        if era_val    is not None: prior_parts.append(f"ERA {era_val:.2f}")
        if fip_val    is not None: prior_parts.append(f"FIP {fip_val:.2f}")
        if whip_val   is not None: prior_parts.append(f"WHIP {whip_val:.2f}")
        if k_pct_val  is not None: prior_parts.append(f"K% {k_pct_val * 100:.1f}%")
        if bb_pct_val is not None: prior_parts.append(f"BB% {bb_pct_val * 100:.1f}%")
        if prior_parts:
            lines.append(f"**Prior-season:** {' · '.join(prior_parts)}")

        # Last-5-starts rolling stats
        l5_era  = getattr(feat, f"{prefix}_last5_era",  None)
        l5_whip = getattr(feat, f"{prefix}_last5_whip", None)
        rest    = getattr(feat, f"{prefix}_days_rest",  None)

        roll_parts = []
        if l5_era  is not None: roll_parts.append(f"ERA {l5_era:.2f}")
        if l5_whip is not None: roll_parts.append(f"WHIP {l5_whip:.2f}")
        if rest    is not None: roll_parts.append(f"{int(rest)}d rest")
        if roll_parts:
            lines.append(f"**Last 5 starts:** {' · '.join(roll_parts)}")

        # 1st-inning specific (season-to-date before today)
        fi_era  = getattr(feat, f"{prefix}_first_inn_era",      None)
        fi_k    = getattr(feat, f"{prefix}_first_inn_k_pct",    None)
        fi_bb   = getattr(feat, f"{prefix}_first_inn_bb_pct",   None)
        fi_hard = getattr(feat, f"{prefix}_first_inn_hard_pct", None)

        fi_parts = []
        if fi_era  is not None: fi_parts.append(f"ERA {fi_era:.2f}")
        if fi_k    is not None: fi_parts.append(f"K% {fi_k * 100:.0f}%")
        if fi_bb   is not None: fi_parts.append(f"BB% {fi_bb * 100:.0f}%")
        if fi_hard is not None: fi_parts.append(f"Hard contact {fi_hard * 100:.0f}%")
        if fi_parts:
            lines.append(f"**1st-inning this season:** {' · '.join(fi_parts)}")

    # Hold records: fraction of starts where they held the opponent scoreless in the 1st
    if hold_records:
        rec_parts = []
        for yr in sorted(hold_records):
            record = hold_records[yr]
            try:
                h, s = record.split("/")
                pct = f"{int(h) / int(s) * 100:.0f}%"
                rec_parts.append(f"'{str(yr)[-2:]}: {record} ({pct})")
            except Exception:
                rec_parts.append(f"'{str(yr)[-2:]}: {record}")
        lines.append(f"**Scoreless 1st inns:** {' · '.join(rec_parts)}")

    return "\n".join(lines) if lines else "No stats available yet."


def _build_pitcher_stats_embeds(target_date: str) -> list[dict[str, Any]]:
    """One embed per game showing both starters' key stats."""
    db = SessionLocal()
    try:
        games = db.query(Game).filter(Game.game_date == target_date).order_by(Game.game_time).all()
        if not games:
            return [{"title": f"Pitcher Stats — {target_date}", "description": "No games found.", "color": _COLOR_GRAY}]

        # Collect all pitcher DB IDs for hold records
        all_db_ids: set[int] = set()
        game_gps: dict[int, Any] = {}
        for game in games:
            gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
            game_gps[game.id] = gp
            if gp:
                if gp.home_sp_id: all_db_ids.add(gp.home_sp_id)
                if gp.away_sp_id: all_db_ids.add(gp.away_sp_id)

        current_year = int(target_date[:4])
        record_seasons = sorted({2025, current_year})
        hold_records = _load_pitcher_hold_records(db, list(all_db_ids), record_seasons)

        embeds = []
        for game in games:
            gp = game_gps.get(game.id)
            feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()

            away_name  = gp.away_sp.name if gp and gp.away_sp else None
            home_name  = gp.home_sp.name if gp and gp.home_sp else None
            away_db_id = gp.away_sp_id if gp else None
            home_db_id = gp.home_sp_id if gp else None

            away_records = hold_records.get(away_db_id, {}) if away_db_id else {}
            home_records = hold_records.get(home_db_id, {}) if home_db_id else {}

            away_stats = _fmt_sp_stats("away_sp", feat, away_records)
            home_stats = _fmt_sp_stats("home_sp", feat, home_records)

            title = f"{game.away_team} @ {game.home_team}"
            game_time_str = _fmt_game_time(game.game_time)
            if game_time_str:
                title += f"  ·  {game_time_str}"

            embeds.append({
                "title": title,
                "color": _COLOR_GRAY,
                "fields": [
                    {
                        "name": f"✈️ {away_name or 'TBD'} (Away SP)",
                        "value": away_stats,
                        "inline": False,
                    },
                    {
                        "name": f"🏠 {home_name or 'TBD'} (Home SP)",
                        "value": home_stats,
                        "inline": False,
                    },
                ],
            })

        return embeds

    finally:
        db.close()


def _run_odds_refresh() -> str:
    """Run the odds refresh pipeline and return a status message."""
    try:
        from scripts.refresh_odds import refresh_odds
        refresh_odds()
        return "✅ Odds refresh complete. Lines updated for today's games."
    except Exception as exc:
        logger.exception("Odds refresh failed")
        return f"❌ Odds refresh failed: {exc}"


def _ensure_tomorrow_pipeline(target_date: str) -> None:
    """Run the daily pipeline for target_date if no predictions exist yet."""
    from scripts.run_daily import run_daily
    db = SessionLocal()
    try:
        games = db.query(Game).filter(Game.game_date == target_date).all()
        has_predictions = any(
            db.query(NrfiFeatures).filter_by(game_id=g.id).first() is not None
            for g in games
        )
    finally:
        db.close()

    if not has_predictions:
        logger.info("No predictions found for %s — running pipeline.", target_date)
        run_daily(target_date=target_date)


@bot.tree.command(name="tomorrow-picks", description="Show tomorrow's NRFI picks privately (only you can see).")
async def tomorrow_picks(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    from datetime import timedelta
    target_date = str(date.today() + timedelta(days=1))

    await asyncio.get_event_loop().run_in_executor(
        None, _ensure_tomorrow_pipeline, target_date
    )

    embeds_data = await asyncio.get_event_loop().run_in_executor(
        None, _build_picks_embeds, target_date
    )
    embeds = [discord.Embed.from_dict(e) for e in embeds_data]

    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i + 10]
        await interaction.followup.send(embeds=chunk, ephemeral=True)


@bot.tree.command(name="yrfi-signals", description="Show today's YRFI signal games (market 60%+ NRFI) privately.")
async def yrfi_signals(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    target_date = str(date.today())
    embed_data = await asyncio.get_event_loop().run_in_executor(
        None, _build_yrfi_signals_embed, target_date
    )
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="season-record", description="Show season W/L record for model picks and YRFI signal.")
async def season_record(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    embed_data = await asyncio.get_event_loop().run_in_executor(
        None, _build_season_record_embed
    )
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="refresh-odds", description="Refresh today's odds lines from the sportsbook API.")
async def refresh_odds_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    msg = await asyncio.get_event_loop().run_in_executor(None, _run_odds_refresh)
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="yesterday-picks", description="Show yesterday's results for model picks and YRFI signal.")
async def yesterday_picks(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    embed_data = await asyncio.get_event_loop().run_in_executor(
        None, _build_yesterday_embed
    )
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="pitcher-stats", description="Show today's starting pitcher stats and 1st-inning hold records.")
async def pitcher_stats(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    target_date = str(date.today())
    embeds_data = await asyncio.get_event_loop().run_in_executor(
        None, _build_pitcher_stats_embeds, target_date
    )
    embeds = [discord.Embed.from_dict(e) for e in embeds_data]
    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i + 10]
        await interaction.followup.send(embeds=chunk, ephemeral=True)


if __name__ == "__main__":
    bot.run(BOT_TOKEN)
