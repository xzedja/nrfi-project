"""
backend/data/fetch_today.py

Fetches today's MLB schedule and probable starters from the MLB Stats API
(the same source that powers baseballsavant.mlb.com/probable-pitchers).

No API key required — this is MLB's public Stats API.

Primary function:
  fetch_schedule(date_str)  →  list of game dicts
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests

logger = logging.getLogger(__name__)

_MLB_SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    "?sportId=1&date={date}&hydrate=probablePitcher,team,venue,officials"
)

_REQUEST_TIMEOUT = 10  # seconds


def fetch_schedule(date_str: str | None = None) -> list[dict[str, Any]]:
    """
    Return a list of game dicts for the given date (default: today).

    Each dict contains:
      game_pk (int)                  : MLB game primary key
      game_date (str)                : YYYY-MM-DD
      game_time (str)                : ISO datetime string (UTC)
      venue_name (str | None)        : MLB venue name, e.g. "Wrigley Field"
      home_team (str)                : team abbreviation, e.g. "MIL"
      away_team (str)                : team abbreviation, e.g. "NYM"
      home_sp_id (int | None)        : MLB pitcher ID, None if not yet announced
      home_sp_name (str | None)      : pitcher full name
      away_sp_id (int | None)        : MLB pitcher ID
      away_sp_name (str | None)      : pitcher full name
      hp_ump_id (int | None)         : MLB umpire person ID (None if not yet posted)
      hp_ump_name (str | None)       : HP umpire full name

    Returns an empty list if no games are scheduled or the API is unreachable.
    """
    target_date = date_str or str(date.today())
    url = _MLB_SCHEDULE_URL.format(date=target_date)

    try:
        response = requests.get(url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.error("Failed to fetch MLB schedule for %s: %s", target_date, exc)
        return []

    games = []
    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            # Skip non-regular-season games (spring training, all-star, etc.)
            game_type = game.get("gameType", "")
            if game_type not in ("R", "P", "F", "D", "L", "W"):
                continue

            home = game["teams"]["home"]
            away = game["teams"]["away"]

            home_pitcher = home.get("probablePitcher") or {}
            away_pitcher = away.get("probablePitcher") or {}

            venue_name = game.get("venue", {}).get("name")

            hp_ump_id = None
            hp_ump_name = None
            for official in game.get("officials", []):
                if official.get("officialType", "").lower() in ("home plate", "hp"):
                    person = official.get("official", {})
                    hp_ump_id = person.get("id")
                    hp_ump_name = person.get("fullName")
                    break

            games.append({
                "game_pk": game["gamePk"],
                "game_date": target_date,
                "game_time": game.get("gameDate"),
                "venue_name": venue_name,
                "home_team": home["team"].get("abbreviation", ""),
                "away_team": away["team"].get("abbreviation", ""),
                "home_sp_id": home_pitcher.get("id"),
                "home_sp_name": home_pitcher.get("fullName"),
                "away_sp_id": away_pitcher.get("id"),
                "away_sp_name": away_pitcher.get("fullName"),
                "hp_ump_id": int(hp_ump_id) if hp_ump_id else None,
                "hp_ump_name": hp_ump_name,
            })

    logger.info("Fetched %d games for %s from MLB Stats API.", len(games), target_date)
    return games
