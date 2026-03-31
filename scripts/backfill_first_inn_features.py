"""
scripts/backfill_first_inn_features.py

Backfills the 6 first-inning Statcast feature columns in nrfi_features for all
existing rows where those columns are NULL:
    home_sp_first_inn_k_pct
    home_sp_first_inn_bb_pct
    home_sp_first_inn_hard_pct
    away_sp_first_inn_k_pct
    away_sp_first_inn_bb_pct
    away_sp_first_inn_hard_pct

Run AFTER migrate_add_first_inn_features.py.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_first_inn_features.py
    DATABASE_URL=postgresql://... python scripts/backfill_first_inn_features.py --season 2024
    DATABASE_URL=postgresql://... python scripts/backfill_first_inn_features.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import extract
from sqlalchemy.orm import aliased

sys.path.insert(0, ".")

from backend.data.build_features import _pitcher_rolling_features, _precompute_pitcher_starts
from backend.data.fetch_stats import _fetch_statcast_season
from backend.db.models import Game, GamePitchers, NrfiFeatures, Pitcher
from backend.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def backfill(season: int | None = None, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        seasons_query = (
            db.query(extract("year", Game.game_date).label("yr"))
            .join(NrfiFeatures, Game.id == NrfiFeatures.game_id)
            .filter(NrfiFeatures.home_sp_first_inn_k_pct.is_(None))
            .distinct()
            .order_by("yr")
        )
        seasons = [int(row.yr) for row in seasons_query]

        if season is not None:
            seasons = [s for s in seasons if s == season]

        if not seasons:
            logger.info("No rows with NULL first-inning features found — nothing to do.")
            return

        logger.info("Seasons to backfill: %s", seasons)

        for s in seasons:
            logger.info("=== Season %s ===", s)

            logger.info("  Loading Statcast data...")
            try:
                season_df = _fetch_statcast_season(s)
                pitcher_starts = _precompute_pitcher_starts(season_df)
                logger.info("  Computed starts for %d pitchers", len(pitcher_starts))
            except Exception:
                logger.warning("  Could not load Statcast for %s — skipping.", s)
                continue

            HomeSP = aliased(Pitcher)
            AwaySP = aliased(Pitcher)

            rows = (
                db.query(NrfiFeatures, Game, HomeSP, AwaySP)
                .join(Game, NrfiFeatures.game_id == Game.id)
                .join(GamePitchers, Game.id == GamePitchers.game_id)
                .outerjoin(HomeSP, GamePitchers.home_sp_id == HomeSP.id)
                .outerjoin(AwaySP, GamePitchers.away_sp_id == AwaySP.id)
                .filter(
                    extract("year", Game.game_date) == s,
                    NrfiFeatures.home_sp_first_inn_k_pct.is_(None),
                )
                .order_by(Game.game_date)
                .all()
            )

            logger.info("  %d rows to update", len(rows))
            updated = 0

            for feat, game, hsp, asp in rows:
                game_date_str = str(game.game_date)

                h_roll = _pitcher_rolling_features(
                    pitcher_starts.get(hsp.external_id) if hsp else None,
                    game_date_str,
                )
                a_roll = _pitcher_rolling_features(
                    pitcher_starts.get(asp.external_id) if asp else None,
                    game_date_str,
                )

                if not dry_run:
                    feat.home_sp_first_inn_k_pct    = h_roll["first_inn_k_pct"]
                    feat.home_sp_first_inn_bb_pct   = h_roll["first_inn_bb_pct"]
                    feat.home_sp_first_inn_hard_pct = h_roll["first_inn_hard_pct"]
                    feat.away_sp_first_inn_k_pct    = a_roll["first_inn_k_pct"]
                    feat.away_sp_first_inn_bb_pct   = a_roll["first_inn_bb_pct"]
                    feat.away_sp_first_inn_hard_pct = a_roll["first_inn_hard_pct"]
                updated += 1

            if not dry_run:
                db.commit()
                logger.info("  Updated %d rows for season %s.", updated, s)
            else:
                logger.info("  [dry-run] Would update %d rows for season %s.", updated, s)

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill first-inning K%/BB%/hard contact% into nrfi_features."
    )
    parser.add_argument("--season", type=int, default=None, help="Limit to a specific season")
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing to DB")
    args = parser.parse_args()
    backfill(season=args.season, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
