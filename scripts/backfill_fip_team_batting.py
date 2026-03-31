"""
scripts/backfill_fip_team_batting.py

Patches home_sp_fip, away_sp_fip, home_team_obp, away_team_obp,
home_team_slg, away_team_slg in existing nrfi_features rows.

These columns were added after the initial feature build, so existing rows
have all NULLs. This script updates them without rebuilding everything.

Run AFTER migrate_add_fip_team_obp.py.

Usage:
    python scripts/backfill_fip_team_batting.py
    python scripts/backfill_fip_team_batting.py --season 2024
    python scripts/backfill_fip_team_batting.py --start-season 2020 --end-season 2025
"""

from __future__ import annotations

import argparse
import logging
import sys
from statistics import median
from typing import Any

import pybaseball
from sqlalchemy import extract
from sqlalchemy.orm import Session, aliased

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.db.models import Game, GamePitchers, NrfiFeatures, Pitcher
from backend.db.session import SessionLocal


# ---------------------------------------------------------------------------
# Pitcher FIP (reuses same 3-season blend logic as build_features.py)
# ---------------------------------------------------------------------------

def _load_sp_fip(season: int, pitcher_mlb_ids: list[int]) -> dict[int, float | None]:
    """
    Return mlbam_id → blended FIP for the given season's pitchers.
    Uses same 3-season IP-weighted blend (5x/3x/2x) as build_features.py.
    """
    if not pitcher_mlb_ids:
        return {}

    pybaseball.cache.enable()

    prior_seasons = [season - 1, season - 2, season - 3]
    recency_weights = {season - 1: 5, season - 2: 3, season - 3: 2}

    season_dfs: dict[int, Any] = {}
    for s in prior_seasons:
        logger.info("  Loading Fangraphs pitching stats for %s...", s)
        try:
            df = pybaseball.pitching_stats(s, s, qual=1)
            if df is not None and not df.empty:
                df.columns = [str(c).strip() for c in df.columns]
                season_dfs[s] = df
        except Exception:
            logger.warning("  Could not load Fangraphs pitching stats for %s.", s)

    if not season_dfs:
        return {mid: None for mid in pitcher_mlb_ids}

    most_recent_df = season_dfs[max(season_dfs)]
    fip_vals = most_recent_df["FIP"].dropna().tolist() if "FIP" in most_recent_df.columns else []
    league_fip = median(fip_vals) if fip_vals else None

    # Build fg_id → {season: {fip, ip}}
    fg_season_stats: dict[int, dict[int, dict]] = {}
    for s, df in season_dfs.items():
        if "FIP" not in df.columns or "IDfg" not in df.columns:
            continue
        for _, row in df.iterrows():
            fg_id = row.get("IDfg")
            if fg_id is None or fg_id != fg_id:
                continue
            fg_id = int(fg_id)
            ip = float(row.get("IP") or 0)
            fip = row.get("FIP")
            fg_season_stats.setdefault(fg_id, {})[s] = {"fip": fip, "ip": ip}

    # MLB ID → Fangraphs ID
    try:
        id_map = pybaseball.playerid_reverse_lookup(pitcher_mlb_ids, key_type="mlbam")
    except Exception:
        return {mid: league_fip for mid in pitcher_mlb_ids}

    mlbam_to_fg: dict[int, int] = {}
    if id_map is not None and not id_map.empty:
        for _, row in id_map.iterrows():
            mlbam = row.get("key_mlbam") or row.get("mlbam_id")
            fg = row.get("key_fangraphs") or row.get("fangraphs_id")
            if mlbam is not None and fg is not None:
                mlbam_to_fg[int(mlbam)] = int(fg)

    def _blend_fip(fg_id: int) -> float | None:
        seasons_data = fg_season_stats.get(fg_id, {})
        if not seasons_data:
            return league_fip
        total_weight = 0.0
        weighted_sum = 0.0
        for s, sdata in seasons_data.items():
            val = sdata.get("fip")
            ip = sdata.get("ip", 0.0)
            rw = recency_weights.get(s, 1)
            if val is not None and ip > 0:
                w = ip * rw
                weighted_sum += val * w
                total_weight += w
        return weighted_sum / total_weight if total_weight > 0 else league_fip

    result: dict[int, float | None] = {}
    for mlbam_id in pitcher_mlb_ids:
        fg_id = mlbam_to_fg.get(mlbam_id)
        result[mlbam_id] = _blend_fip(fg_id) if fg_id is not None else league_fip

    return result


# ---------------------------------------------------------------------------
# Team batting OBP/SLG (same logic as build_features.py)
# ---------------------------------------------------------------------------

_FG_TEAM_TO_ABBREV: dict[str, str] = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CWS": "CWS", "CIN": "CIN", "CLE": "CLE",
    "COL": "COL", "DET": "DET", "HOU": "HOU", "KCR": "KC",
    "LAA": "LAA", "LAD": "LAD", "MIA": "MIA", "MIL": "MIL",
    "MIN": "MIN", "NYM": "NYM", "NYY": "NYY", "OAK": "ATH",
    "PHI": "PHI", "PIT": "PIT", "SDP": "SD",  "SEA": "SEA",
    "SFG": "SF",  "STL": "STL", "TBR": "TB",  "TEX": "TEX",
    "TOR": "TOR", "WSN": "WSH", "ATH": "ATH",
}


def _load_team_batting(season: int) -> tuple[dict[str, dict], dict[str, float | None]]:
    """Return team_abbrev → {obp, slg} for prior season, plus league averages."""
    pybaseball.cache.enable()
    prior = season - 1
    logger.info("  Loading Fangraphs team batting stats for %s (prior: %s)...", season, prior)

    try:
        df = pybaseball.batting_stats(prior, prior, qual=50)
    except Exception:
        return {}, {"obp": None, "slg": None}

    if df is None or df.empty:
        return {}, {"obp": None, "slg": None}

    df.columns = [str(c).strip() for c in df.columns]
    if "Team" not in df.columns or "OBP" not in df.columns or "SLG" not in df.columns:
        return {}, {"obp": None, "slg": None}

    team_data: dict[str, dict[str, list]] = {}
    for _, row in df.iterrows():
        fg_team = str(row.get("Team", "")).strip()
        abbrev = _FG_TEAM_TO_ABBREV.get(fg_team, fg_team)
        pa = float(row.get("PA") or 0)
        obp = row.get("OBP")
        slg = row.get("SLG")
        if pa > 0 and obp is not None and slg is not None:
            d = team_data.setdefault(abbrev, {"pa": [], "obp": [], "slg": []})
            d["pa"].append(pa)
            d["obp"].append(float(obp) * pa)
            d["slg"].append(float(slg) * pa)

    result: dict[str, dict] = {}
    all_obp, all_slg = [], []
    for abbrev, d in team_data.items():
        total_pa = sum(d["pa"])
        if total_pa > 0:
            obp_val = sum(d["obp"]) / total_pa
            slg_val = sum(d["slg"]) / total_pa
            result[abbrev] = {"obp": round(obp_val, 4), "slg": round(slg_val, 4)}
            all_obp.append(obp_val)
            all_slg.append(slg_val)

    league_avg = {
        "obp": round(median(all_obp), 4) if all_obp else None,
        "slg": round(median(all_slg), 4) if all_slg else None,
    }
    logger.info("  Loaded team batting for %d teams.", len(result))
    return result, league_avg


# ---------------------------------------------------------------------------
# Main backfill
# ---------------------------------------------------------------------------

def backfill_season(season: int, db: Session, batch_size: int = 500) -> None:
    logger.info("=== Backfilling FIP + team OBP/SLG for season %s ===", season)

    HomeSP = aliased(Pitcher)
    AwaySP = aliased(Pitcher)

    rows = (
        db.query(Game, GamePitchers, NrfiFeatures, HomeSP, AwaySP)
        .join(GamePitchers, GamePitchers.game_id == Game.id)
        .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
        .outerjoin(HomeSP, GamePitchers.home_sp_id == HomeSP.id)
        .outerjoin(AwaySP, GamePitchers.away_sp_id == AwaySP.id)
        .filter(
            extract("year", Game.game_date) == season,
            NrfiFeatures.home_sp_fip.is_(None),
        )
        .order_by(Game.game_date)
        .all()
    )

    if not rows:
        logger.info("  No rows need updating for %s.", season)
        return

    logger.info("  %d rows to update for season %s.", len(rows), season)

    # Collect unique pitcher IDs
    all_mlb_ids = list({
        p.external_id
        for _, _, _, hsp, asp in rows
        for p in (hsp, asp)
        if p is not None
    })

    sp_fip = _load_sp_fip(season, all_mlb_ids)
    team_batting, league_avg_batting = _load_team_batting(season)

    updated = 0
    for i, (game, gp, feat, hsp, asp) in enumerate(rows):
        h_fip = sp_fip.get(hsp.external_id) if hsp else None
        a_fip = sp_fip.get(asp.external_id) if asp else None

        ht_bat = team_batting.get(game.home_team, league_avg_batting)
        at_bat = team_batting.get(game.away_team, league_avg_batting)

        feat.home_sp_fip = h_fip
        feat.away_sp_fip = a_fip
        feat.home_team_obp = ht_bat.get("obp")
        feat.away_team_obp = at_bat.get("obp")
        feat.home_team_slg = ht_bat.get("slg")
        feat.away_team_slg = at_bat.get("slg")
        updated += 1

        if (i + 1) % batch_size == 0:
            db.commit()
            logger.info("  [%d/%d] committed.", i + 1, len(rows))

    db.commit()
    logger.info("  Season %s done — updated %d rows.", season, updated)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill FIP and team OBP/SLG in nrfi_features.")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--start-season", type=int, default=2015)
    parser.add_argument("--end-season", type=int, default=2026)
    args = parser.parse_args()

    seasons = [args.season] if args.season else list(range(args.start_season, args.end_season + 1))

    db = SessionLocal()
    try:
        for season in seasons:
            backfill_season(season, db)
        logger.info("Backfill complete.")
    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
