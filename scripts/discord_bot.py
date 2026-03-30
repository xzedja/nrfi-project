"""
scripts/discord_bot.py

Discord gateway bot for NRFI slash commands.

Connects outbound to Discord — works behind CGNAT with no public URL required.

Commands:
  /today-record   — public embed showing today's picks W/L record
  /display-picks  — ephemeral embed showing today's full picks (only visible to requester)

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

_VALUE_PLAY_THRESHOLD = float(os.environ.get("VALUE_PLAY_THRESHOLD_PP", "2")) / 100.0

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


def _edge_color(edge: float | None) -> int:
    if edge is None:
        return _COLOR_GRAY
    if edge >= _VALUE_PLAY_THRESHOLD:
        return _COLOR_GREEN
    if edge > 0:
        return _COLOR_YELLOW
    return _COLOR_RED


def _recommendation(edge: float) -> str:
    edge_pct = f"{abs(edge) * 100:.0f}%"
    if edge >= _VALUE_PLAY_THRESHOLD:
        return f"🟢 **Model strongly favors NRFI** — {edge_pct} above market"
    elif edge > 0:
        return f"🟡 **Model leans NRFI** — slight disagreement with market"
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
        description = f"{pitchers_line}{odds_line}{data_line}\n{_recommendation(edge)}"
    elif model is not None:
        nrfi_pct = f"{model * 100:.0f}%"
        description = f"{pitchers_line}{odds_line}Model {nrfi_pct} · Mkt N/A\n⚪ No lines yet — model gives NRFI {nrfi_pct}"
    else:
        description = "No prediction available."

    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": _edge_color(edge),
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

        value_plays = sum(1 for p in preds if p.get("edge") is not None and p["edge"] >= _VALUE_PLAY_THRESHOLD)
        leans       = sum(1 for p in preds if p.get("edge") is not None and 0 < p["edge"] < _VALUE_PLAY_THRESHOLD)
        no_lines    = sum(1 for p in preds if p.get("edge") is None)

        parts = [f"{len(preds)} games today"]
        if value_plays:
            parts.append(f"**{value_plays} value play{'s' if value_plays != 1 else ''}**")
        if leans:
            parts.append(f"{leans} lean{'s' if leans != 1 else ''}")
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


if __name__ == "__main__":
    bot.run(BOT_TOKEN)
