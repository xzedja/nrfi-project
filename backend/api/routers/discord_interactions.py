"""
backend/api/routers/discord_interactions.py

Handles incoming Discord interactions (slash commands).

Discord POSTs to /discord/interactions whenever a user invokes a slash command
in any server where the bot is installed.

Supported commands:
  /today-record  — shows today's picks record (W/L for finished games, pending for live)

Setup:
  1. Set DISCORD_PUBLIC_KEY in your environment (from Discord Developer Portal).
  2. In the Discord Developer Portal, set the Interactions Endpoint URL to:
       https://your-domain:4000/discord/interactions
  3. Run scripts/register_slash_commands.py once to register /today-record.
"""

from __future__ import annotations

import logging
from datetime import date, timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.db.models import Game, NrfiFeatures, GamePitchers, Pitcher
from backend.db.session import SessionLocal
from sqlalchemy.orm import aliased

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discord", tags=["discord"])

# Discord interaction types
_PING = 1
_APPLICATION_COMMAND = 2

# Discord response types
_PONG = 1
_CHANNEL_MESSAGE_WITH_SOURCE = 4

# Edge threshold — must match post_discord.py
_VALUE_PLAY_THRESHOLD = 0.02

_COLOR_GREEN  = 0x2ECC71
_COLOR_YELLOW = 0xF1C40F
_COLOR_GRAY   = 0x95A5A6


def _verify_signature(public_key: str, signature: str, timestamp: str, body: bytes) -> bool:
    """Verify Discord's Ed25519 request signature."""
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
        vk = VerifyKey(bytes.fromhex(public_key))
        vk.verify((timestamp + body.decode()).encode(), bytes.fromhex(signature))
        return True
    except Exception:
        return False


def _build_today_record_embed(target_date: str, db: Session) -> dict[str, Any]:
    """Build a Discord embed showing today's picks record."""
    games = db.query(Game).filter(Game.game_date == target_date).all()

    HomeSP = aliased(Pitcher)
    AwaySP = aliased(Pitcher)

    picks = []
    for game in games:
        feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()
        if feat is None or feat.p_nrfi_model is None or feat.p_nrfi_market is None:
            continue

        edge = feat.p_nrfi_model - feat.p_nrfi_market
        if edge <= 0:
            continue  # Only track positive-edge picks

        # Get pitcher names
        gp = db.query(GamePitchers).filter_by(game_id=game.id).first()
        home_sp_name = None
        away_sp_name = None
        if gp:
            home_sp_name = gp.home_sp.name if gp.home_sp else None
            away_sp_name = gp.away_sp.name if gp.away_sp else None

        outcome = game.nrfi  # True = NRFI happened, False = YRFI, None = pending

        picks.append({
            "matchup": f"{game.away_team} @ {game.home_team}",
            "pitchers": f"{away_sp_name} vs {home_sp_name}" if away_sp_name and home_sp_name else None,
            "edge": edge,
            "outcome": outcome,
            "p_model": feat.p_nrfi_model,
        })

    if not picks:
        return {
            "title": f"Today's Record — {target_date}",
            "description": "No picks with positive edge found for today.",
            "color": _COLOR_GRAY,
        }

    wins   = sum(1 for p in picks if p["outcome"] is True)
    losses = sum(1 for p in picks if p["outcome"] is False)
    pending = sum(1 for p in picks if p["outcome"] is None)

    # Header line
    record_parts = []
    if wins or losses:
        record_parts.append(f"**{wins}W - {losses}L**")
    if pending:
        record_parts.append(f"{pending} pending")
    record_str = "  ·  ".join(record_parts) if record_parts else "All pending"

    # Per-game lines
    lines = []
    for p in picks:
        if p["outcome"] is True:
            icon = "✅"
        elif p["outcome"] is False:
            icon = "❌"
        else:
            icon = "⏳"

        edge_str = f"+{p['edge'] * 100:.0f}%"
        model_str = f"{p['p_model'] * 100:.0f}%"
        line = f"{icon} **{p['matchup']}** — Model {model_str} · Edge {edge_str}"
        if p["pitchers"]:
            line += f"\n   ↳ {p['pitchers']}"
        lines.append(line)

    color = _COLOR_GREEN if wins > losses else (_COLOR_YELLOW if wins == losses else _COLOR_GRAY)

    return {
        "title": f"NRFI Picks — {target_date}",
        "description": f"{record_str}\n\n" + "\n\n".join(lines),
        "color": color,
    }


@router.post("/interactions")
async def interactions(request: Request) -> Response:
    """
    Entry point for all Discord interactions.
    Discord will POST here for every slash command invocation.
    """
    settings = get_settings()

    if not settings.discord_public_key:
        raise HTTPException(status_code=503, detail="Discord interactions not configured.")

    # Verify the request signature
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp  = request.headers.get("X-Signature-Timestamp", "")
    body = await request.body()

    if not _verify_signature(settings.discord_public_key, signature, timestamp, body):
        raise HTTPException(status_code=401, detail="Invalid request signature.")

    payload: dict[str, Any] = await request.json()
    interaction_type = payload.get("type")

    # Discord requires us to respond to PINGs immediately
    if interaction_type == _PING:
        return Response(content='{"type":1}', media_type="application/json")

    if interaction_type == _APPLICATION_COMMAND:
        command_name = payload.get("data", {}).get("name", "")

        if command_name == "today-record":
            target_date = str(date.today())
            db = SessionLocal()
            try:
                embed = _build_today_record_embed(target_date, db)
            finally:
                db.close()

            return Response(
                content=__import__("json").dumps({
                    "type": _CHANNEL_MESSAGE_WITH_SOURCE,
                    "data": {"embeds": [embed]},
                }),
                media_type="application/json",
            )

    # Unknown command — acknowledge silently
    return Response(
        content=__import__("json").dumps({
            "type": _CHANNEL_MESSAGE_WITH_SOURCE,
            "data": {"content": "Unknown command.", "flags": 64},  # ephemeral
        }),
        media_type="application/json",
    )
