"""
backend/data/fetch_lineups.py

Fetches starting lineup batting orders from the MLB Stats API.

For completed games, uses the boxscore endpoint (actual batting orders used).
For today's games, falls back gracefully if lineups aren't posted yet.

No API key required — this is MLB's public Stats API.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
_REQUEST_TIMEOUT = 10


def fetch_batting_lineup(game_pk: int) -> dict[str, list[dict]] | None:
    """
    Fetch the starting batting order for a game from the MLB Stats API boxscore.

    Returns:
        {
            'home': [{'player_id': int, 'batting_order': int}, ...],  # sorted 1-9
            'away': [{'player_id': int, 'batting_order': int}, ...]
        }
        or None if lineup data is unavailable (game not yet played, API error).

    battingOrder values in the API are "100", "200", ..., "900" for starters;
    "101", "102", ... for mid-game substitutes (we skip those).
    """
    url = _BOXSCORE_URL.format(game_pk=game_pk)
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.debug("Failed to fetch boxscore for game_pk %s: %s", game_pk, exc)
        return None

    teams = data.get("teams", {})
    result: dict[str, list[dict]] = {}

    for side in ("home", "away"):
        batters: list[dict] = []
        players = teams.get(side, {}).get("players", {})
        for _player_key, player_data in players.items():
            raw_order = player_data.get("battingOrder")
            if raw_order is None:
                continue
            order_int = int(raw_order)
            if order_int % 100 != 0:
                continue  # skip substitutes (e.g. 101, 201...)
            player_id = player_data.get("person", {}).get("id")
            if player_id:
                batters.append({
                    "player_id": int(player_id),
                    "batting_order": order_int // 100,  # 1-9
                })
        batters.sort(key=lambda x: x["batting_order"])
        result[side] = batters

    if not result.get("home") and not result.get("away"):
        return None

    return result


def fetch_batting_lineups_bulk(
    game_pks: list[int],
    delay_secs: float = 0.2,
) -> dict[int, dict[str, list[dict]] | None]:
    """
    Fetch batting lineups for a list of game_pks.

    Returns dict of game_pk → lineup dict (or None if unavailable).
    Adds a small delay between requests to avoid hammering the API.
    """
    results: dict[int, dict[str, list[dict]] | None] = {}
    for i, game_pk in enumerate(game_pks):
        results[game_pk] = fetch_batting_lineup(game_pk)
        if delay_secs > 0 and i < len(game_pks) - 1:
            time.sleep(delay_secs)
    return results


def update_lineup_obp_for_date(target_date: str) -> int:
    """
    Fetch batting lineups from MLB Stats API for all games on target_date and
    update home_lineup_obp / away_lineup_obp in nrfi_features.

    Uses prior-season Fangraphs batting stats for individual batter OBP.
    Falls back to team-level average (via SeasonStartImputer) if a batter has
    no prior-season data.

    Returns the number of games updated.
    Non-fatal: games without lineups posted yet are silently skipped.
    """
    import sys
    from statistics import median

    import pybaseball

    sys.path.insert(0, ".")
    from backend.db.models import Game, NrfiFeatures
    from backend.db.session import SessionLocal

    season = int(target_date[:4])
    prior_season = season - 1

    db = SessionLocal()
    try:
        games_today = (
            db.query(Game, NrfiFeatures)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(Game.game_date == target_date)
            .all()
        )

        if not games_today:
            return 0

        # Load prior-season batting OBP per Fangraphs player ID
        pybaseball.cache.enable()
        fg_to_obp: dict[int, float] = {}
        try:
            bat_df = pybaseball.batting_stats(prior_season, prior_season, qual=1)
            if bat_df is not None and not bat_df.empty:
                bat_df.columns = [str(c).strip() for c in bat_df.columns]
                if "IDfg" in bat_df.columns and "OBP" in bat_df.columns:
                    for _, row in bat_df.iterrows():
                        fg_id = row.get("IDfg")
                        obp = row.get("OBP")
                        if fg_id is not None and obp is not None:
                            fg_to_obp[int(fg_id)] = float(obp)
        except Exception:
            logger.warning("Could not load Fangraphs batting stats for lineup OBP.")

        league_avg_obp = round(median(fg_to_obp.values()), 4) if fg_to_obp else 0.320

        # Fetch lineups for all games (one request per game)
        lineup_by_pk: dict[int, dict | None] = {}
        all_player_ids: list[int] = []
        for game, _ in games_today:
            if not game.external_id:
                continue
            lineup = fetch_batting_lineup(game.external_id)
            lineup_by_pk[game.external_id] = lineup
            if lineup:
                for side in ("home", "away"):
                    all_player_ids.extend(b["player_id"] for b in lineup.get(side, []))

        # Batch MLB → Fangraphs ID mapping
        mlbam_to_fg: dict[int, int] = {}
        if all_player_ids and fg_to_obp:
            try:
                id_df = pybaseball.playerid_reverse_lookup(
                    list(set(all_player_ids)), key_type="mlbam"
                )
                if id_df is not None and not id_df.empty:
                    for _, row in id_df.iterrows():
                        mlbam = row.get("key_mlbam") or row.get("mlbam_id")
                        fg = row.get("key_fangraphs") or row.get("fangraphs_id")
                        if mlbam is not None and fg is not None:
                            mlbam_to_fg[int(mlbam)] = int(fg)
            except Exception:
                logger.warning("playerid_reverse_lookup failed — using league avg for lineup OBP.")

        def _avg_obp(player_ids: list[int]) -> float | None:
            if len(player_ids) < 4:
                return None
            vals = [
                fg_to_obp.get(mlbam_to_fg.get(pid), league_avg_obp)
                for pid in player_ids
            ]
            return round(sum(vals) / len(vals), 4)

        updated = 0
        for game, feat in games_today:
            if not game.external_id:
                continue
            lineup = lineup_by_pk.get(game.external_id)
            if not lineup:
                continue
            home_pids = [b["player_id"] for b in lineup.get("home", [])]
            away_pids = [b["player_id"] for b in lineup.get("away", [])]
            home_obp = _avg_obp(home_pids)
            away_obp = _avg_obp(away_pids)
            if home_obp is not None or away_obp is not None:
                feat.home_lineup_obp = home_obp
                feat.away_lineup_obp = away_obp
                updated += 1

        db.commit()
        logger.info("Lineup OBP updated for %d game(s) on %s.", updated, target_date)
        return updated

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
