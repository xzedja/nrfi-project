"""
backend/data/build_features.py

Builds NrfiFeatures rows for each game in a season.

Feature sourcing:
  - SP stats (ERA, WHIP, K%, BB%, HR/9): prior-season Fangraphs data via pybaseball.
    Using the prior season avoids any in-season data leakage.
    Pitchers with no prior-season data receive league-median values.
  - Team first-inning run rates: rolling averages from the games table,
    using only games played before the target game date (same season).
  - Park factor: placeholder 1.0 — to be improved with real park data later.

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

import pybaseball
from sqlalchemy.orm import Session, aliased
from sqlalchemy import extract

sys.path.insert(0, ".")

from backend.db.models import Game, GamePitchers, NrfiFeatures, Pitcher
from backend.db.session import SessionLocal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SP stats (Fangraphs, prior season)
# ---------------------------------------------------------------------------

def _load_sp_stats(season: int, pitcher_mlb_ids: list[int]) -> dict[int, dict[str, Any]]:
    """
    Return a dict of mlbam_id → SP stat dict for the given season.

    Pulls Fangraphs pitching leaderboard data and maps it to MLB IDs via
    pybaseball's playerid_reverse_lookup. Missing pitchers get league medians.

    Stat keys: era, whip, k_pct, bb_pct, hr9
    """
    if not pitcher_mlb_ids:
        return {}

    pybaseball.cache.enable()

    # Fangraphs pitching leaderboard for the season (qual=1 = min 1 IP, gets everyone)
    logger.info("Loading Fangraphs pitching stats for season %s", season)
    try:
        fg_df = pybaseball.pitching_stats(season, season, qual=1)
    except Exception:
        logger.warning("Could not load Fangraphs pitching stats for %s — using league averages.", season)
        return {}

    if fg_df is None or fg_df.empty:
        return {}

    # Normalise column names — Fangraphs occasionally changes capitalisation
    fg_df.columns = [str(c).strip() for c in fg_df.columns]

    # Resolve the HR/9 column name (Fangraphs uses 'HR/9' but sometimes 'HR9')
    hr9_col = next((c for c in fg_df.columns if c.replace("/", "").replace(" ", "").upper() == "HR9"), None)

    # Compute league medians for fallback
    def _safe_median(col: str) -> float | None:
        if col not in fg_df.columns:
            return None
        vals = fg_df[col].dropna().tolist()
        return median(vals) if vals else None

    league_avg: dict[str, Any] = {
        "era": _safe_median("ERA"),
        "whip": _safe_median("WHIP"),
        "k_pct": _safe_median("K%"),
        "bb_pct": _safe_median("BB%"),
        "hr9": _safe_median(hr9_col) if hr9_col else None,
    }

    # Build Fangraphs ID → stats lookup (column is 'IDfg', not 'playerid')
    fg_to_stats: dict[int, dict[str, Any]] = {}
    for _, row in fg_df.iterrows():
        fg_id = row.get("IDfg")
        if fg_id is None or (fg_id != fg_id):  # skip NaN
            continue
        fg_to_stats[int(fg_id)] = {
            "era": row.get("ERA"),
            "whip": row.get("WHIP"),
            "k_pct": row.get("K%"),
            "bb_pct": row.get("BB%"),
            "hr9": row.get(hr9_col) if hr9_col else None,
        }

    # Map MLB IDs → Fangraphs IDs
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

    result: dict[int, dict[str, Any]] = {}
    for mlbam_id in pitcher_mlb_ids:
        fg_id = mlbam_to_fg.get(mlbam_id)
        if fg_id is not None and fg_id in fg_to_stats:
            result[mlbam_id] = fg_to_stats[fg_id]
        else:
            result[mlbam_id] = league_avg.copy()

    return result


# ---------------------------------------------------------------------------
# Team rolling first-inning stats (from games table)
# ---------------------------------------------------------------------------

def _precompute_team_stats(
    db: Session, season: int
) -> dict[tuple[str, date], dict[str, float | None]]:
    """
    For every (team, game_date) pair in the season, compute the team's
    rolling first-inning run rates using only games played BEFORE that date.

    Returns a dict keyed by (team, game_date).
    """
    games = (
        db.query(Game)
        .filter(extract("year", Game.game_date) == season)
        .order_by(Game.game_date)
        .all()
    )

    # Build per-team history: team → list of (date, runs_scored, runs_allowed)
    team_history: dict[str, list[tuple[date, int | None, int | None]]] = {}
    for g in games:
        for team, scored, allowed in (
            (g.home_team, g.inning_1_home_runs, g.inning_1_away_runs),
            (g.away_team, g.inning_1_away_runs, g.inning_1_home_runs),
        ):
            team_history.setdefault(team, []).append((g.game_date, scored, allowed))

    # For each game date, compute stats using only prior games
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

            if not prior:
                result[key] = {
                    "first_inn_runs_scored_per_game": None,
                    "first_inn_runs_allowed_per_game": None,
                }
            else:
                scored_vals = [sc for sc, _ in prior if sc is not None]
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

        # Collect all unique MLB pitcher IDs in this season
        all_mlb_ids: list[int] = list({
            p.external_id
            for _, _, hsp, asp in rows
            for p in (hsp, asp)
            if p is not None
        })

        # Load prior-season SP stats from Fangraphs
        sp_stats = _load_sp_stats(season - 1, all_mlb_ids)

        # Compute league averages as fallback (median across all loaded stats)
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

        # Precompute rolling team stats for the entire season
        team_stats = _precompute_team_stats(db, season)

        inserted = 0
        skipped = 0

        for game, gp, hsp, asp in rows:
            if db.query(NrfiFeatures).filter_by(game_id=game.id).first():
                skipped += 1
                continue

            h = sp_stats.get(hsp.external_id, league_avg) if hsp else league_avg
            a = sp_stats.get(asp.external_id, league_avg) if asp else league_avg

            ht = team_stats.get((game.home_team, game.game_date), {})
            at = team_stats.get((game.away_team, game.game_date), {})

            db.add(NrfiFeatures(
                game_id=game.id,

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

                home_team_first_inn_runs_per_game=ht.get("first_inn_runs_scored_per_game"),
                away_team_first_inn_runs_per_game=at.get("first_inn_runs_scored_per_game"),

                park_factor=1.0,
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
