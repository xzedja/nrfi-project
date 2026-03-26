"""
backend/data/fetch_stats.py

Fetches MLB game and pitcher data using pybaseball (Statcast).

Coverage: 2015–present (Statcast era only).

Primary functions:
  - load_games_for_season(season)          → list of game dicts with 1st-inning runs + nrfi label
  - load_starting_pitchers_for_season(season) → dict of game_pk → SP info
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pybaseball

logger = logging.getLogger(__name__)

STATCAST_MIN_SEASON = 2015

# In-process cache so load_games_for_season and load_starting_pitchers_for_season
# can both be called for the same season without re-fetching the data.
_season_cache: dict[int, pd.DataFrame] = {}

# Only pull columns we actually need — keeps memory low on large season pulls
_STATCAST_COLS = [
    "game_pk",
    "game_date",
    "home_team",
    "away_team",
    "inning",
    "inning_topbot",
    "pitcher",
    "p_throws",
    "at_bat_number",
    "pitch_number",
    "post_bat_score",
]


def _season_date_range(season: int) -> tuple[date, date]:
    """Return approximate start/end dates covering a full MLB season."""
    # Opening day is typically late March; season ends early October (or later for playoffs)
    return date(season, 4, 1), date(season, 10, 5)


def _fetch_statcast_season(season: int) -> pd.DataFrame:
    """
    Download Statcast data for a full season, chunked by ~4-week windows to
    keep memory manageable. Returns only the columns defined in _STATCAST_COLS.

    Raises ValueError for seasons before Statcast coverage (pre-2015).
    """
    if season < STATCAST_MIN_SEASON:
        raise ValueError(
            f"Statcast data is only available from {STATCAST_MIN_SEASON}; got {season}."
        )

    if season in _season_cache:
        logger.info("Using in-process cache for season %s", season)
        return _season_cache[season]

    # Enable pybaseball's local disk cache to avoid re-downloading on reruns
    pybaseball.cache.enable()

    start, end = _season_date_range(season)
    chunks: list[pd.DataFrame] = []
    chunk_start = start

    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=27), end)
        logger.info("Fetching Statcast %s → %s", chunk_start, chunk_end)

        df = pybaseball.statcast(
            start_dt=str(chunk_start),
            end_dt=str(chunk_end),
            verbose=False,
        )

        if df is not None and not df.empty:
            available_cols = [c for c in _STATCAST_COLS if c in df.columns]
            chunks.append(df[available_cols])

        chunk_start = chunk_end + timedelta(days=1)

    if not chunks:
        logger.warning("No Statcast data returned for season %s.", season)
        return pd.DataFrame(columns=_STATCAST_COLS)

    result = pd.concat(chunks, ignore_index=True)
    _season_cache[season] = result
    return result


def load_games_for_season(season: int) -> list[dict[str, Any]]:
    """
    Return a list of game dicts for every MLB game in the given season.

    Each dict contains:
      game_pk (int)              : MLB game primary key
      game_date (str)            : YYYY-MM-DD
      home_team (str)            : home team abbreviation
      away_team (str)            : away team abbreviation
      inning_1_away_runs (int)   : runs scored by away team in top of 1st
      inning_1_home_runs (int)   : runs scored by home team in bottom of 1st
      nrfi (bool)                : True when both teams scored 0 in the 1st

    Note: post_bat_score starts at 0 in the 1st inning, so max(post_bat_score)
    within a half-inning equals the runs scored by the batting team that half.
    """
    raw = _fetch_statcast_season(season)
    if raw.empty:
        return []

    first = raw[raw["inning"] == 1].copy()
    first["game_date"] = first["game_date"].astype(str)

    # Max post_bat_score per half-inning = runs scored by that batting team
    half_runs = (
        first
        .groupby(["game_pk", "game_date", "home_team", "away_team", "inning_topbot"])["post_bat_score"]
        .max()
        .reset_index()
        .rename(columns={"post_bat_score": "runs"})
    )

    pivot = half_runs.pivot_table(
        index=["game_pk", "game_date", "home_team", "away_team"],
        columns="inning_topbot",
        values="runs",
        aggfunc="max",
    ).reset_index()
    pivot.columns.name = None

    pivot = pivot.rename(columns={"Top": "inning_1_away_runs", "Bot": "inning_1_home_runs"})

    # Guard against missing half-inning (e.g. walk-off in top of 1st is impossible,
    # but rain delays or data gaps can occasionally leave one side absent)
    for col in ("inning_1_away_runs", "inning_1_home_runs"):
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["inning_1_away_runs"] = pivot["inning_1_away_runs"].fillna(0).astype(int)
    pivot["inning_1_home_runs"] = pivot["inning_1_home_runs"].fillna(0).astype(int)

    pivot["nrfi"] = (pivot["inning_1_away_runs"] == 0) & (pivot["inning_1_home_runs"] == 0)
    pivot["game_pk"] = pivot["game_pk"].astype(int)

    return pivot.to_dict(orient="records")


def load_starting_pitchers_for_season(season: int) -> dict[int, dict[str, Any]]:
    """
    Return a mapping of game_pk → starting pitcher info for the given season.

    Each value is a dict:
      home_sp_id (int | None)     : MLB pitcher ID for the home team's starter
      away_sp_id (int | None)     : MLB pitcher ID for the away team's starter
      home_sp_throws (str | None) : "L" or "R"
      away_sp_throws (str | None) : "L" or "R"

    Identifies SPs as the pitcher who threw the very first pitch of each
    team's half of the 1st inning:
      - Top of 1st: away team bats → pitcher = home SP
      - Bot of 1st: home team bats → pitcher = away SP
    """
    raw = _fetch_statcast_season(season)
    if raw.empty:
        return {}

    first = raw[raw["inning"] == 1].copy()

    # Sort so groupby().first() gives us the earliest pitch thrown
    first = first.sort_values(
        ["game_pk", "inning_topbot", "at_bat_number", "pitch_number"]
    )

    first_pitches = (
        first
        .groupby(["game_pk", "inning_topbot"])[["pitcher", "p_throws"]]
        .first()
        .reset_index()
    )

    result: dict[int, dict[str, Any]] = {}

    for _, row in first_pitches.iterrows():
        pk = int(row["game_pk"])
        if pk not in result:
            result[pk] = {
                "home_sp_id": None,
                "away_sp_id": None,
                "home_sp_throws": None,
                "away_sp_throws": None,
            }

        pitcher_id = int(row["pitcher"]) if pd.notna(row["pitcher"]) else None
        throws = row["p_throws"] if pd.notna(row["p_throws"]) else None

        if row["inning_topbot"] == "Top":
            # Away bats → home team is pitching → home SP
            result[pk]["home_sp_id"] = pitcher_id
            result[pk]["home_sp_throws"] = throws
        else:
            # Home bats → away team is pitching → away SP
            result[pk]["away_sp_id"] = pitcher_id
            result[pk]["away_sp_throws"] = throws

    return result
