"""
backend/data/build_features.py

Builds NrfiFeatures rows for each game in a season.

Feature sourcing:
  - SP prior-season stats (ERA, WHIP, K%, BB%, HR/9): Fangraphs via pybaseball.
  - SP rolling recent-form (last 5 starts, within-season):
      - ERA proxy, WHIP proxy, first-inning ERA, avg velocity, velocity trend
      - Computed from Statcast pitch data for games BEFORE each target game.
  - Team first-inning run rates: rolling averages from the games table,
    using only games played before the target game date (same season).
  - Park factor: placeholder 1.0 — to be improved with real park data later.

Anti-leakage: only stats from games strictly BEFORE the target game date are used.

Usage:
    DATABASE_URL=postgresql://... python -m backend.data.build_features
    DATABASE_URL=postgresql://... python -m backend.data.build_features --season 2023
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from statistics import median
from typing import Any

import pandas as pd
import pybaseball
from sqlalchemy import extract
from sqlalchemy.orm import Session, aliased

sys.path.insert(0, ".")

from backend.data.fetch_stats import _fetch_statcast_season
from backend.data.fetch_weather import PARK_INFO, fetch_weather_for_park_daterange, get_weather_for_game
from backend.db.models import Game, GamePitchers, GameUmpire, NrfiFeatures, Pitcher
from backend.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Events that count as hits or walks for WHIP numerator
_HIT_WALK_EVENTS = frozenset({
    "single", "double", "triple", "home_run",
    "walk", "hit_by_pitch",
})


# ---------------------------------------------------------------------------
# SP prior-season stats (Fangraphs)
# ---------------------------------------------------------------------------

def _load_sp_stats(season: int, pitcher_mlb_ids: list[int]) -> dict[int, dict[str, Any]]:
    """
    Return a dict of mlbam_id → SP stat dict for the given season.

    Blends the 3 prior seasons (season-1, season-2, season-3) using IP-weighted
    averages with recency weights (5x, 3x, 2x). This produces more stable
    pitcher profiles than a single prior season, and handles missed seasons
    (injury, minors) gracefully by using available years.

    Missing pitchers (no data in any prior season) get league medians.

    Stat keys: era, whip, k_pct, bb_pct, hr9
    """
    if not pitcher_mlb_ids:
        return {}

    pybaseball.cache.enable()

    # Recency weights: season-1 = 5x, season-2 = 3x, season-3 = 2x
    prior_seasons = [season - 1, season - 2, season - 3]
    recency_weights = {season - 1: 5, season - 2: 3, season - 3: 2}

    # Load Fangraphs data for all 3 prior seasons
    season_dfs: dict[int, pd.DataFrame] = {}
    for s in prior_seasons:
        logger.info("Loading Fangraphs pitching stats for season %s", s)
        try:
            df = pybaseball.pitching_stats(s, s, qual=1)
            if df is not None and not df.empty:
                df.columns = [str(c).strip() for c in df.columns]
                season_dfs[s] = df
        except Exception:
            logger.warning("Could not load Fangraphs pitching stats for %s — skipping.", s)

    if not season_dfs:
        logger.warning("No Fangraphs data available for any prior season — using empty stats.")
        return {}

    # Use the most recent available season to compute league medians
    most_recent_df = season_dfs[max(season_dfs)]
    hr9_col = next(
        (c for c in most_recent_df.columns if c.replace("/", "").replace(" ", "").upper() == "HR9"),
        None,
    )

    def _safe_median(df: pd.DataFrame, col: str) -> float | None:
        if col not in df.columns:
            return None
        vals = df[col].dropna().tolist()
        return median(vals) if vals else None

    league_avg: dict[str, Any] = {
        "era":    _safe_median(most_recent_df, "ERA"),
        "whip":   _safe_median(most_recent_df, "WHIP"),
        "k_pct":  _safe_median(most_recent_df, "K%"),
        "bb_pct": _safe_median(most_recent_df, "BB%"),
        "hr9":    _safe_median(most_recent_df, hr9_col) if hr9_col else None,
    }

    # Build fg_id → {season: {stat: value, ip: float}} lookup across all seasons
    fg_season_stats: dict[int, dict[int, dict[str, Any]]] = {}
    for s, df in season_dfs.items():
        s_hr9_col = next(
            (c for c in df.columns if c.replace("/", "").replace(" ", "").upper() == "HR9"),
            None,
        )
        for _, row in df.iterrows():
            fg_id = row.get("IDfg")
            if fg_id is None or (fg_id != fg_id):
                continue
            fg_id = int(fg_id)
            ip = row.get("IP") or 0.0
            fg_season_stats.setdefault(fg_id, {})[s] = {
                "era":    row.get("ERA"),
                "whip":   row.get("WHIP"),
                "k_pct":  row.get("K%"),
                "bb_pct": row.get("BB%"),
                "hr9":    row.get(s_hr9_col) if s_hr9_col else None,
                "ip":     float(ip),
            }

    logger.info("Reverse-looking up %d pitcher MLB IDs", len(pitcher_mlb_ids))
    try:
        id_map = pybaseball.playerid_reverse_lookup(pitcher_mlb_ids, key_type="mlbam")
    except Exception:
        logger.warning("playerid_reverse_lookup failed — all pitchers will use league averages.")
        return {mid: league_avg.copy() for mid in pitcher_mlb_ids}

    mlbam_to_fg: dict[int, int] = {}
    if id_map is not None and not id_map.empty:
        for _, row in id_map.iterrows():
            mlbam = row.get("key_mlbam") or row.get("mlbam_id")
            fg = row.get("key_fangraphs") or row.get("fangraphs_id")
            if mlbam is not None and fg is not None:
                mlbam_to_fg[int(mlbam)] = int(fg)

    def _blend_stats(fg_id: int) -> dict[str, Any]:
        """IP-weighted blend across available prior seasons with recency multiplier."""
        seasons_data = fg_season_stats.get(fg_id, {})
        if not seasons_data:
            return league_avg.copy()

        blended: dict[str, Any] = {}
        for stat in ("era", "whip", "k_pct", "bb_pct", "hr9"):
            total_weight = 0.0
            weighted_sum = 0.0
            for s, sdata in seasons_data.items():
                val = sdata.get(stat)
                ip = sdata.get("ip", 0.0)
                rw = recency_weights.get(s, 1)
                if val is not None and ip > 0:
                    w = ip * rw
                    weighted_sum += val * w
                    total_weight += w
            if total_weight > 0:
                blended[stat] = weighted_sum / total_weight
            else:
                blended[stat] = league_avg.get(stat)
        return blended

    result: dict[int, dict[str, Any]] = {}
    for mlbam_id in pitcher_mlb_ids:
        fg_id = mlbam_to_fg.get(mlbam_id)
        if fg_id is not None:
            result[mlbam_id] = _blend_stats(fg_id)
        else:
            result[mlbam_id] = league_avg.copy()

    return result


# ---------------------------------------------------------------------------
# Team rolling first-inning stats (from games table)
# ---------------------------------------------------------------------------

def _precompute_team_stats(
    db: Session, season: int, min_games: int = 10
) -> dict[tuple[str, date], dict[str, float | None]]:
    """
    For every (team, game_date) pair in the season, compute the team's
    rolling first-inning run rates using only games played BEFORE that date.

    If fewer than min_games have been played in the current season, falls back
    to the prior season's full-season average to avoid noisy early-season values.
    """
    # --- Prior season averages (fallback for early-season games) ---
    prior_season_games = (
        db.query(Game)
        .filter(
            extract("year", Game.game_date) == season - 1,
            Game.inning_1_home_runs.isnot(None),
            Game.inning_1_away_runs.isnot(None),
        )
        .all()
    )

    prior_team_data: dict[str, list[tuple[int, int]]] = {}
    for g in prior_season_games:
        prior_team_data.setdefault(g.home_team, []).append(
            (g.inning_1_home_runs, g.inning_1_away_runs)
        )
        prior_team_data.setdefault(g.away_team, []).append(
            (g.inning_1_away_runs, g.inning_1_home_runs)
        )

    prior_season_avg: dict[str, dict[str, float | None]] = {}
    for team, data in prior_team_data.items():
        scored_vals  = [sc for sc, _ in data if sc is not None]
        allowed_vals = [al for _, al in data if al is not None]
        prior_season_avg[team] = {
            "first_inn_runs_scored_per_game": (
                sum(scored_vals) / len(scored_vals) if scored_vals else None
            ),
            "first_inn_runs_allowed_per_game": (
                sum(allowed_vals) / len(allowed_vals) if allowed_vals else None
            ),
        }

    # --- Current season rolling stats ---
    games = (
        db.query(Game)
        .filter(extract("year", Game.game_date) == season)
        .order_by(Game.game_date)
        .all()
    )

    team_history: dict[str, list[tuple[date, int | None, int | None]]] = {}
    for g in games:
        for team, scored, allowed in (
            (g.home_team, g.inning_1_home_runs, g.inning_1_away_runs),
            (g.away_team, g.inning_1_away_runs, g.inning_1_home_runs),
        ):
            team_history.setdefault(team, []).append((g.game_date, scored, allowed))

    result: dict[tuple[str, date], dict[str, float | None]] = {}
    for g in games:
        for team in (g.home_team, g.away_team):
            key = (team, g.game_date)
            if key in result:
                continue

            prior = [
                (sc, al)
                for d, sc, al in team_history.get(team, [])
                if d < g.game_date
            ]

            if len(prior) < min_games:
                # Too few games — use prior season average to avoid noisy values
                result[key] = prior_season_avg.get(team, {
                    "first_inn_runs_scored_per_game": None,
                    "first_inn_runs_allowed_per_game": None,
                })
            else:
                scored_vals  = [sc for sc, _ in prior if sc is not None]
                allowed_vals = [al for _, al in prior if al is not None]
                result[key] = {
                    "first_inn_runs_scored_per_game": (
                        sum(scored_vals) / len(scored_vals) if scored_vals else None
                    ),
                    "first_inn_runs_allowed_per_game": (
                        sum(allowed_vals) / len(allowed_vals) if allowed_vals else None
                    ),
                }

    return result


# ---------------------------------------------------------------------------
# Within-season pitcher rolling stats (from Statcast)
# ---------------------------------------------------------------------------

def _precompute_pitcher_starts(season_df: pd.DataFrame) -> dict[int, pd.DataFrame]:
    """
    Compute per-start stats for every pitcher in the season's Statcast data.

    Returns a dict mapping pitcher MLBAM id → DataFrame with one row per start,
    sorted chronologically. Columns:
        game_date        : YYYY-MM-DD string
        first_inn_runs   : runs scored in inning 1 while this pitcher was pitching
        ip_half          : number of half-innings pitched (IP ≈ ip_half / 2)
        hits_walks       : H + BB faced (WHIP numerator)
        runs_allowed     : total runs scored across all innings pitched
        avg_velo         : mean release_speed for the start (None if unavailable)
    """
    has_velo = "release_speed" in season_df.columns
    has_events = "events" in season_df.columns

    results: dict[int, pd.DataFrame] = {}

    for pitcher_id, pdf in season_df.groupby("pitcher"):
        starts = []
        for game_pk, gdf in pdf.groupby("game_pk"):
            game_date = str(gdf["game_date"].iloc[0])[:10]

            # First-inning runs: max post_bat_score in inning 1
            inn1 = gdf[gdf["inning"] == 1]
            first_inn_runs = int(inn1["post_bat_score"].max()) if not inn1.empty else 0

            # IP proxy: count half-innings pitched
            ip_half = int(gdf.groupby(["inning", "inning_topbot"]).ngroups)

            # Total runs allowed: sum of score deltas across each half-inning
            total_runs = 0
            for (_, _), hdf in gdf.groupby(["inning", "inning_topbot"]):
                delta = hdf["post_bat_score"].max() - hdf["post_bat_score"].min()
                total_runs += max(0, int(delta))

            # Hits + walks from events column (end-of-AB events only)
            hits_walks: int | None = None
            if has_events:
                end_ab = gdf[gdf["events"].notna()]
                hits_walks = int(end_ab["events"].isin(_HIT_WALK_EVENTS).sum())

            # Average velocity
            avg_velo: float | None = None
            if has_velo:
                velo = gdf["release_speed"].dropna()
                if not velo.empty:
                    avg_velo = float(velo.mean())

            starts.append({
                "game_date": game_date,
                "first_inn_runs": first_inn_runs,
                "ip_half": ip_half,
                "hits_walks": hits_walks,
                "runs_allowed": total_runs,
                "avg_velo": avg_velo,
            })

        if starts:
            results[int(pitcher_id)] = (
                pd.DataFrame(starts)
                .sort_values("game_date")
                .reset_index(drop=True)
            )

    return results


def _pitcher_rolling_features(
    starts_df: pd.DataFrame | None,
    before_date: str,
    n: int = 5,
) -> dict[str, float | None]:
    """
    Compute rolling pitcher features from prior starts strictly before before_date.

    Returns dict with keys:
        last5_era       : ERA proxy (runs/IP * 9) over last n starts
        last5_whip      : WHIP proxy (hits+walks / IP) over last n starts
        first_inn_era   : first-inning ERA proxy (first_inn_runs/start * 9, season-to-date)
        avg_velo        : mean fastball velocity over last n starts
        velo_trend      : last-start avg velo minus n-start avg (negative = declining)
        days_rest       : days since most recent prior start (None if first start of season)
    """
    _null = {k: None for k in ("last5_era", "last5_whip", "first_inn_era", "avg_velo", "velo_trend", "days_rest")}

    if starts_df is None or starts_df.empty:
        return _null

    prior = starts_df[starts_df["game_date"] < before_date]
    if prior.empty:
        return _null

    last_n = prior.tail(n)

    # ERA proxy
    total_runs = float(last_n["runs_allowed"].sum())
    total_ip = float(last_n["ip_half"].sum()) / 2.0
    last5_era = round(total_runs / total_ip * 9, 4) if total_ip > 0 else None

    # WHIP proxy
    hw_series = last_n["hits_walks"].dropna()
    last5_whip: float | None = None
    if not hw_series.empty and total_ip > 0:
        last5_whip = round(float(hw_series.sum()) / total_ip, 4)

    # First-inning ERA (all prior starts, not just last-n)
    n_prior = len(prior)
    fi_era = round(float(prior["first_inn_runs"].sum()) / n_prior * 9, 4) if n_prior > 0 else None

    # Average velocity
    velo_vals = last_n["avg_velo"].dropna()
    avg_velo = round(float(velo_vals.mean()), 2) if not velo_vals.empty else None

    # Velocity trend: last-start velo vs n-start avg
    velo_trend: float | None = None
    if avg_velo is not None and len(last_n) >= 2:
        last_velo = last_n.iloc[-1]["avg_velo"]
        if pd.notna(last_velo):
            velo_trend = round(float(last_velo) - avg_velo, 2)

    # Days rest: days between most recent prior start and target game date
    days_rest: float | None = None
    last_start_date = prior.iloc[-1]["game_date"]
    try:
        from datetime import date as _date
        delta = _date.fromisoformat(before_date) - _date.fromisoformat(last_start_date)
        days_rest = float(delta.days)
    except Exception:
        pass

    return {
        "last5_era": last5_era,
        "last5_whip": last5_whip,
        "first_inn_era": fi_era,
        "avg_velo": avg_velo,
        "velo_trend": velo_trend,
        "days_rest": days_rest,
    }


# ---------------------------------------------------------------------------
# Weather features
# ---------------------------------------------------------------------------

def _precompute_weather(
    db: Session, season: int
) -> dict[int, dict[str, Any]]:
    """
    Fetch game-time weather for every game in the season.

    Batches API calls by park (one Open-Meteo call per park covering the full
    season date range) to avoid per-game requests.

    Returns dict of game_id → weather dict (temperature_f, wind_speed_mph,
    wind_out_mph, is_dome).
    """
    from backend.data.fetch_weather import _wind_out_component

    games = (
        db.query(Game)
        .filter(extract("year", Game.game_date) == season)
        .order_by(Game.game_date)
        .all()
    )

    # Group games by park
    park_games: dict[str, list[Game]] = {}
    for g in games:
        if g.park:
            park_games.setdefault(g.park, []).append(g)

    result: dict[int, dict[str, Any]] = {}

    for park, park_game_list in park_games.items():
        info = PARK_INFO.get(park)
        if info is None:
            logger.debug("  Weather: unknown park '%s' — skipping.", park)
            for g in park_game_list:
                result[g.id] = {"temperature_f": None, "wind_speed_mph": None, "wind_out_mph": None, "is_dome": 0.0}
            continue

        if info["is_dome"]:
            for g in park_game_list:
                result[g.id] = {"temperature_f": None, "wind_speed_mph": None, "wind_out_mph": None, "is_dome": 1.0}
            continue

        dates = [str(g.game_date) for g in park_game_list]
        start_date, end_date = min(dates), max(dates)

        logger.info("  Weather: fetching %s (%s → %s) — %d games", park, start_date, end_date, len(park_game_list))
        hourly_data = fetch_weather_for_park_daterange(park, start_date, end_date)

        for g in park_game_list:
            date_str = str(g.game_date)
            date_hours = hourly_data.get(date_str, {})

            # Use 19:00 local as default game time for historical games
            row = date_hours.get(19) or date_hours.get(18) or date_hours.get(20)
            if row is None:
                result[g.id] = {"temperature_f": None, "wind_speed_mph": None, "wind_out_mph": None, "is_dome": 0.0}
                continue

            temp_f, wind_spd, wind_dir = row
            wind_out = (
                _wind_out_component(wind_spd, wind_dir, info["outfield_dir"])
                if wind_spd is not None and wind_dir is not None
                else None
            )
            result[g.id] = {
                "temperature_f": round(temp_f, 1) if temp_f is not None else None,
                "wind_speed_mph": round(wind_spd, 1) if wind_spd is not None else None,
                "wind_out_mph": wind_out,
                "is_dome": 0.0,
            }

    # Games with no park set
    for g in games:
        if g.id not in result:
            result[g.id] = {"temperature_f": None, "wind_speed_mph": None, "wind_out_mph": None, "is_dome": 0.0}

    return result


# ---------------------------------------------------------------------------
# Umpire features
# ---------------------------------------------------------------------------

def _precompute_umpire_features(
    db: Session, season: int
) -> dict[int, float | None]:
    """
    Compute each HP umpire's historical NRFI rate relative to league average,
    using only games BEFORE the target game date (anti-leakage).

    Feature = regression-weighted (ump_nrfi_rate - league_nrfi_rate).
    Weight = min(1.0, prior_games / 150) — full weight after 150 games.

    Returns dict of game_id → ump_nrfi_rate_above_avg (None if no umpire assigned).
    """
    from bisect import bisect_left

    # Load ALL umpire assignments with game results (all seasons for full history)
    all_ump_rows = (
        db.query(GameUmpire.ump_id, Game.game_date, Game.nrfi)
        .join(Game, GameUmpire.game_id == Game.id)
        .filter(Game.nrfi.isnot(None))
        .order_by(Game.game_date)
        .all()
    )

    if not all_ump_rows:
        logger.warning("  Umpire: no GameUmpire records found — ump feature will be None for all games.")
        return {}

    # Build per-umpire sorted history: ump_id → [(date, nrfi_label), ...]
    ump_history: dict[int, list[tuple[date, bool]]] = {}
    total_nrfi = 0
    total_games = 0
    for ump_id, game_date, nrfi_label in all_ump_rows:
        ump_history.setdefault(ump_id, []).append((game_date, bool(nrfi_label)))
        total_nrfi += int(nrfi_label)
        total_games += 1

    league_avg_nrfi = total_nrfi / total_games if total_games > 0 else 0.5

    # Load target season games with umpire assignments
    season_ump_rows = (
        db.query(GameUmpire.game_id, GameUmpire.ump_id, Game.game_date)
        .join(Game, GameUmpire.game_id == Game.id)
        .filter(extract("year", Game.game_date) == season)
        .all()
    )

    result: dict[int, float | None] = {}
    for game_id, ump_id, game_date in season_ump_rows:
        history = ump_history.get(ump_id, [])
        # Binary search: count records strictly before game_date
        idx = bisect_left(history, (game_date,))
        prior = history[:idx]

        if not prior:
            result[game_id] = None
            continue

        n = len(prior)
        nrfi_count = sum(1 for _, label in prior if label)
        ump_rate = nrfi_count / n
        weight = min(1.0, n / 150.0)
        result[game_id] = round(weight * (ump_rate - league_avg_nrfi), 4)

    return result


# ---------------------------------------------------------------------------
# First-inning park factors (computed from historical DB data)
# ---------------------------------------------------------------------------

def _precompute_park_factors(db: Session, before_season: int) -> dict[str, float]:
    """
    Compute first-inning park factors for all known parks using data from all
    seasons strictly before before_season. Returns dict of park_name -> park_factor.

    Park factor = ratio of avg first-inning runs at that park vs league average,
    regressed toward 1.0 for small samples (full weight after 200 games).

    Anti-leakage: only uses data from prior seasons, never the current season.
    """
    games = (
        db.query(Game)
        .filter(
            extract("year", Game.game_date) < before_season,
            Game.park.isnot(None),
            Game.inning_1_home_runs.isnot(None),
            Game.inning_1_away_runs.isnot(None),
        )
        .all()
    )

    if not games:
        return {}

    total_runs = sum(g.inning_1_home_runs + g.inning_1_away_runs for g in games)
    league_avg = total_runs / len(games)

    park_runs: dict[str, list[float]] = {}
    for g in games:
        park_runs.setdefault(g.park, []).append(
            g.inning_1_home_runs + g.inning_1_away_runs
        )

    result: dict[str, float] = {}
    for park, runs_list in park_runs.items():
        n = len(runs_list)
        park_avg = sum(runs_list) / n
        raw_pf = park_avg / league_avg if league_avg > 0 else 1.0
        weight = min(1.0, n / 200.0)
        result[park] = round(weight * raw_pf + (1.0 - weight) * 1.0, 4)

    logger.info(
        "  Computed park factors for %d parks from %d prior-season games (before %s)",
        len(result), len(games), before_season,
    )
    return result


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_features_for_season(season: int) -> None:
    """
    Compute and insert NrfiFeatures for every game in the given season.
    Skips games that already have a features row (idempotent).
    """
    logger.info("=== Building features for season %s ===", season)
    db = SessionLocal()

    try:
        HomeSP = aliased(Pitcher)
        AwaySP = aliased(Pitcher)

        rows = (
            db.query(Game, GamePitchers, HomeSP, AwaySP)
            .join(GamePitchers, Game.id == GamePitchers.game_id)
            .outerjoin(HomeSP, GamePitchers.home_sp_id == HomeSP.id)
            .outerjoin(AwaySP, GamePitchers.away_sp_id == AwaySP.id)
            .filter(extract("year", Game.game_date) == season)
            .order_by(Game.game_date)
            .all()
        )

        logger.info("  Found %d games with pitcher data", len(rows))
        if not rows:
            return

        # Collect all unique MLB pitcher IDs in this season
        all_mlb_ids: list[int] = list({
            p.external_id
            for _, _, hsp, asp in rows
            for p in (hsp, asp)
            if p is not None
        })

        # --- Prior-season Fangraphs stats (for full-season ERA/WHIP/K%/BB%/HR9) ---
        sp_stats = _load_sp_stats(season - 1, all_mlb_ids)

        def _median_stat(key: str) -> float | None:
            vals = [v[key] for v in sp_stats.values() if v.get(key) is not None]
            return median(vals) if vals else None

        league_avg = {
            "era": _median_stat("era"),
            "whip": _median_stat("whip"),
            "k_pct": _median_stat("k_pct"),
            "bb_pct": _median_stat("bb_pct"),
            "hr9": _median_stat("hr9"),
        }

        # --- Within-season rolling stats from Statcast ---
        logger.info("  Loading Statcast data for within-season pitcher rolling stats...")
        try:
            season_df = _fetch_statcast_season(season)
            pitcher_starts = _precompute_pitcher_starts(season_df)
            logger.info("  Precomputed starts for %d pitchers", len(pitcher_starts))
        except Exception:
            logger.warning("  Could not load Statcast data — rolling features will be None.")
            pitcher_starts = {}

        # --- Rolling team first-inning rates ---
        team_stats = _precompute_team_stats(db, season)

        # --- First-inning park factors (prior seasons only) ---
        park_factors = _precompute_park_factors(db, season)

        # --- Weather features ---
        logger.info("  Fetching weather for season %s games...", season)
        weather_map = _precompute_weather(db, season)

        # --- Umpire features ---
        ump_map = _precompute_umpire_features(db, season)

        inserted = 0
        skipped = 0

        for game, gp, hsp, asp in rows:
            if db.query(NrfiFeatures).filter_by(game_id=game.id).first():
                skipped += 1
                continue

            # Prior-season stats
            h = sp_stats.get(hsp.external_id, league_avg) if hsp else league_avg
            a = sp_stats.get(asp.external_id, league_avg) if asp else league_avg

            # Rolling within-season stats
            game_date_str = str(game.game_date)
            h_roll = _pitcher_rolling_features(
                pitcher_starts.get(hsp.external_id) if hsp else None,
                game_date_str,
            )
            a_roll = _pitcher_rolling_features(
                pitcher_starts.get(asp.external_id) if asp else None,
                game_date_str,
            )

            ht = team_stats.get((game.home_team, game.game_date), {})
            at = team_stats.get((game.away_team, game.game_date), {})
            wx = weather_map.get(game.id, {})

            db.add(NrfiFeatures(
                game_id=game.id,

                # Prior-season Fangraphs features
                home_sp_era=h.get("era"),
                home_sp_whip=h.get("whip"),
                home_sp_k_pct=h.get("k_pct"),
                home_sp_bb_pct=h.get("bb_pct"),
                home_sp_hr9=h.get("hr9"),

                away_sp_era=a.get("era"),
                away_sp_whip=a.get("whip"),
                away_sp_k_pct=a.get("k_pct"),
                away_sp_bb_pct=a.get("bb_pct"),
                away_sp_hr9=a.get("hr9"),

                # Within-season rolling features
                home_sp_last5_era=h_roll["last5_era"],
                home_sp_last5_whip=h_roll["last5_whip"],
                home_sp_first_inn_era=h_roll["first_inn_era"],
                home_sp_avg_velo=h_roll["avg_velo"],
                home_sp_velo_trend=h_roll["velo_trend"],
                home_sp_days_rest=h_roll["days_rest"],

                away_sp_last5_era=a_roll["last5_era"],
                away_sp_last5_whip=a_roll["last5_whip"],
                away_sp_first_inn_era=a_roll["first_inn_era"],
                away_sp_avg_velo=a_roll["avg_velo"],
                away_sp_velo_trend=a_roll["velo_trend"],
                away_sp_days_rest=a_roll["days_rest"],

                # Team offense features
                home_team_first_inn_runs_per_game=ht.get("first_inn_runs_scored_per_game"),
                away_team_first_inn_runs_per_game=at.get("first_inn_runs_scored_per_game"),

                # Park and weather
                park_factor=park_factors.get(game.park, 1.0),
                temperature_f=wx.get("temperature_f"),
                wind_speed_mph=wx.get("wind_speed_mph"),
                wind_out_mph=wx.get("wind_out_mph"),
                is_dome=wx.get("is_dome", 0.0),

                # Umpire
                ump_nrfi_rate_above_avg=ump_map.get(game.id),

                nrfi_label=game.nrfi,
                p_nrfi_market=None,
            ))
            inserted += 1

        db.commit()
        logger.info(
            "  Season %s done — inserted: %d, skipped: %d", season, inserted, skipped
        )

    except Exception:
        db.rollback()
        logger.exception("  Error building features for season %s — rolled back.", season)
        raise
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Build NrfiFeatures for a season.")
    parser.add_argument("--season", type=int, default=2023)
    args = parser.parse_args()
    build_features_for_season(args.season)


if __name__ == "__main__":
    main()
