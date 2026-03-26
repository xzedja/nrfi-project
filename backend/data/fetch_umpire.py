"""
backend/data/fetch_umpire.py

Fetches home plate umpire assignments for MLB games via the MLB Stats API.

The schedule endpoint with hydrate=officials returns umpire assignments for
games once they are posted (typically the day before or day of the game).
For historical backfill, the boxscore endpoint always has officials.

Primary functions:
    fetch_umpires_for_date(date_str)   → dict[game_pk → {ump_id, ump_name}]
    fetch_umpire_for_game_pk(game_pk)  → dict | None  (boxscore fallback)
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    "?sportId=1&date={date}&hydrate=officials"
)
_BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
_REQUEST_TIMEOUT = 10


def _extract_hp_umpire(officials: list[dict]) -> dict[str, Any] | None:
    """Pull the Home Plate umpire entry from an officials list."""
    for official in officials:
        if official.get("officialType", "").lower() in ("home plate", "hp"):
            person = official.get("official", {})
            ump_id = person.get("id")
            ump_name = person.get("fullName")
            if ump_id:
                return {"ump_id": int(ump_id), "ump_name": ump_name}
    return None


def fetch_umpires_for_date(date_str: str) -> dict[int, dict[str, Any]]:
    """
    Return HP umpire assignments for all games on date_str.

    Returns: dict of game_pk → {"ump_id": int, "ump_name": str | None}
    Games with no officials posted yet are omitted from the result.
    """
    url = _SCHEDULE_URL.format(date=date_str)
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch umpires for %s: %s", date_str, exc)
        return {}

    result: dict[int, dict[str, Any]] = {}
    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            game_pk = game.get("gamePk")
            if game_pk is None:
                continue
            officials = game.get("officials", [])
            hp = _extract_hp_umpire(officials)
            if hp:
                result[int(game_pk)] = hp

    return result


def fetch_umpire_for_game_pk(game_pk: int) -> dict[str, Any] | None:
    """
    Fetch the HP umpire for a single completed game via the boxscore endpoint.
    Used as a fallback when the schedule hydrate doesn't have officials.

    Returns {"ump_id": int, "ump_name": str | None} or None if unavailable.
    """
    url = _BOXSCORE_URL.format(game_pk=game_pk)
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.debug("Failed to fetch boxscore for game %d: %s", game_pk, exc)
        return None

    officials = data.get("officials", [])
    return _extract_hp_umpire(officials)
