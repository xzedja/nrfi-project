"""
scripts/backfill_lineups.py

Backfills home_lineup_obp and away_lineup_obp in nrfi_features for all
historical games (2015–present).

Lineup OBP = average prior-season OBP of the 9 starters in the batting order,
fetched from the MLB Stats API boxscore. Prior-season OBP comes from Fangraphs
(no leakage — all stats are from before the game date).

Run AFTER migrate_add_lineup_obp.py.

Usage:
    python scripts/backfill_lineups.py
    python scripts/backfill_lineups.py --season 2024
    python scripts/backfill_lineups.py --start-season 2020 --end-season 2024
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from statistics import median
from typing import Any

import pybaseball
from sqlalchemy import extract

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.data.fetch_lineups import fetch_batting_lineup
from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal


# ---------------------------------------------------------------------------
# Fangraphs batting stats cache: season → {fg_id: obp}
# ---------------------------------------------------------------------------

_batting_cache: dict[int, dict[int, float]] = {}
_id_map_cache: dict[int, int] = {}  # mlbam_id → fg_id


def _get_batter_obp_lookup(prior_season: int) -> dict[int, float]:
    """
    Return mlbam_id → prior-season OBP for all known batters.
    Results are cached in-process.
    """
    if prior_season in _batting_cache:
        return _batting_cache[prior_season]

    pybaseball.cache.enable()

    logger.info("Loading Fangraphs batting stats for %s...", prior_season)
    try:
        df = pybaseball.batting_stats(prior_season, prior_season, qual=1)
    except Exception as exc:
        logger.warning("Failed to load Fangraphs batting stats for %s: %s", prior_season, exc)
        _batting_cache[prior_season] = {}
        return {}

    if df is None or df.empty:
        _batting_cache[prior_season] = {}
        return {}

    df.columns = [str(c).strip() for c in df.columns]
    if "IDfg" not in df.columns or "OBP" not in df.columns:
        logger.warning("Expected columns missing from batting stats for %s", prior_season)
        _batting_cache[prior_season] = {}
        return {}

    # Build fg_id → OBP
    fg_to_obp: dict[int, float] = {}
    for _, row in df.iterrows():
        fg_id = row.get("IDfg")
        obp = row.get("OBP")
        if fg_id is not None and obp is not None:
            fg_to_obp[int(fg_id)] = float(obp)

    _batting_cache[prior_season] = fg_to_obp
    logger.info("  Loaded OBP for %d batters (season %s)", len(fg_to_obp), prior_season)
    return fg_to_obp


def _get_mlbam_to_fg_map(mlbam_ids: list[int]) -> dict[int, int]:
    """
    Return mlbam_id → fangraphs_id for the given list of MLB player IDs.
    Results are cached globally across calls.
    """
    uncached = [i for i in mlbam_ids if i not in _id_map_cache]
    if not uncached:
        return {i: _id_map_cache[i] for i in mlbam_ids if i in _id_map_cache}

    logger.info("Looking up Fangraphs IDs for %d new MLB player IDs...", len(uncached))
    try:
        id_df = pybaseball.playerid_reverse_lookup(uncached, key_type="mlbam")
    except Exception as exc:
        logger.warning("playerid_reverse_lookup failed: %s", exc)
        return {}

    if id_df is not None and not id_df.empty:
        for _, row in id_df.iterrows():
            mlbam = row.get("key_mlbam") or row.get("mlbam_id")
            fg = row.get("key_fangraphs") or row.get("fangraphs_id")
            if mlbam is not None and fg is not None:
                _id_map_cache[int(mlbam)] = int(fg)

    return {i: _id_map_cache[i] for i in mlbam_ids if i in _id_map_cache}


def _compute_lineup_obp(
    player_ids: list[int],
    fg_to_obp: dict[int, float],
    league_avg_obp: float,
) -> float | None:
    """
    Compute average prior-season OBP for a batting lineup.

    Players not found in Fangraphs data use the league average as a fallback.
    Returns None if the lineup has fewer than 4 starters.
    """
    if len(player_ids) < 4:
        return None

    # Get Fangraphs ID mapping for all players
    mlbam_to_fg = _get_mlbam_to_fg_map(player_ids)

    obp_vals: list[float] = []
    for pid in player_ids:
        fg_id = mlbam_to_fg.get(pid)
        if fg_id is not None:
            obp = fg_to_obp.get(fg_id)
            obp_vals.append(obp if obp is not None else league_avg_obp)
        else:
            obp_vals.append(league_avg_obp)

    return round(sum(obp_vals) / len(obp_vals), 4) if obp_vals else None


def backfill_season(season: int, db, batch_size: int = 100) -> None:
    """Backfill lineup OBP for all games in the given season."""
    logger.info("--- Backfilling lineup OBP for season %s ---", season)

    # Find games that need lineup OBP (have nrfi_features but NULL lineup)
    rows = (
        db.query(Game, NrfiFeatures)
        .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
        .filter(
            extract("year", Game.game_date) == season,
            NrfiFeatures.home_lineup_obp.is_(None),
        )
        .order_by(Game.game_date)
        .all()
    )

    if not rows:
        logger.info("  No games need lineup backfill for %s", season)
        return

    logger.info("  %d games need lineup OBP for %s", len(rows), season)

    # Load prior-season batting stats once for this season
    prior_season = season - 1
    fg_to_obp = _get_batter_obp_lookup(prior_season)

    # League average OBP (fallback for unknown batters)
    league_avg_obp = (
        round(median(fg_to_obp.values()), 4) if fg_to_obp else 0.320
    )
    logger.info("  League avg OBP for %s: %.3f", prior_season, league_avg_obp)

    updated = 0
    skipped = 0

    for i, (game, feat) in enumerate(rows):
        if game.external_id is None:
            skipped += 1
            continue

        lineup = fetch_batting_lineup(game.external_id)

        if lineup is None:
            skipped += 1
        else:
            home_pids = [b["player_id"] for b in lineup.get("home", [])]
            away_pids = [b["player_id"] for b in lineup.get("away", [])]

            feat.home_lineup_obp = _compute_lineup_obp(home_pids, fg_to_obp, league_avg_obp)
            feat.away_lineup_obp = _compute_lineup_obp(away_pids, fg_to_obp, league_avg_obp)

            if feat.home_lineup_obp is not None or feat.away_lineup_obp is not None:
                updated += 1
            else:
                skipped += 1

        # Commit in batches
        if (i + 1) % batch_size == 0:
            db.commit()
            logger.info(
                "  [%d/%d] Updated: %d  Skipped: %d",
                i + 1, len(rows), updated, skipped,
            )

        # Rate limiting: ~3 req/sec to avoid hammering MLB API
        time.sleep(0.33)

    db.commit()
    logger.info("  Season %s done — updated: %d  skipped: %d", season, updated, skipped)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill lineup OBP in nrfi_features.")
    parser.add_argument("--season", type=int, default=None, help="Single season to backfill")
    parser.add_argument("--start-season", type=int, default=2015)
    parser.add_argument("--end-season", type=int, default=2025)
    args = parser.parse_args()

    seasons = [args.season] if args.season else list(range(args.start_season, args.end_season + 1))

    db = SessionLocal()
    try:
        for season in seasons:
            backfill_season(season, db)
        logger.info("Lineup backfill complete.")
    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
