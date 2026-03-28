"""
scripts/backfill_pitcher_rest.py

Backfills home_sp_days_rest and away_sp_days_rest in nrfi_features for all
existing rows where those columns are NULL.

Loads Statcast data per season to compute each pitcher's per-start dates,
then calculates days since last start before each target game.

Run AFTER migrate_add_pitcher_rest.py.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_pitcher_rest.py
    DATABASE_URL=postgresql://... python scripts/backfill_pitcher_rest.py --season 2024
    DATABASE_URL=postgresql://... python scripts/backfill_pitcher_rest.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as _date

from sqlalchemy import extract

sys.path.insert(0, ".")

from backend.data.build_features import _precompute_pitcher_starts
from backend.data.fetch_stats import _fetch_statcast_season
from backend.db.models import Game, GamePitchers, NrfiFeatures, Pitcher
from backend.db.session import SessionLocal
from sqlalchemy.orm import aliased

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _days_rest(starts_df, before_date: str) -> float | None:
    """Days between pitcher's most recent prior start and before_date."""
    if starts_df is None or starts_df.empty:
        return None
    prior = starts_df[starts_df["game_date"] < before_date]
    if prior.empty:
        return None
    last_start = prior.iloc[-1]["game_date"]
    try:
        delta = _date.fromisoformat(before_date) - _date.fromisoformat(last_start)
        return float(delta.days)
    except Exception:
        return None


def backfill(season: int | None = None, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        seasons_query = (
            db.query(extract("year", Game.game_date).label("yr"))
            .join(NrfiFeatures, Game.id == NrfiFeatures.game_id)
            .filter(NrfiFeatures.home_sp_days_rest.is_(None))
            .distinct()
            .order_by("yr")
        )
        seasons = [int(row.yr) for row in seasons_query]

        if season is not None:
            seasons = [s for s in seasons if s == season]

        if not seasons:
            logger.info("No rows with NULL days_rest found — nothing to do.")
            return

        logger.info("Seasons to backfill: %s", seasons)

        for s in seasons:
            logger.info("=== Season %s ===", s)

            # Load Statcast data for this season
            logger.info("  Loading Statcast data...")
            try:
                season_df = _fetch_statcast_season(s)
                pitcher_starts = _precompute_pitcher_starts(season_df)
                logger.info("  Computed starts for %d pitchers", len(pitcher_starts))
            except Exception:
                logger.warning("  Could not load Statcast for %s — skipping.", s)
                continue

            # Fetch all nrfi_features rows for this season with NULL rest
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
                    NrfiFeatures.home_sp_days_rest.is_(None),
                )
                .order_by(Game.game_date)
                .all()
            )

            logger.info("  %d rows to update", len(rows))
            updated = 0

            for feat, game, hsp, asp in rows:
                game_date_str = str(game.game_date)

                h_rest = _days_rest(
                    pitcher_starts.get(hsp.external_id) if hsp else None,
                    game_date_str,
                )
                a_rest = _days_rest(
                    pitcher_starts.get(asp.external_id) if asp else None,
                    game_date_str,
                )

                if not dry_run:
                    feat.home_sp_days_rest = h_rest
                    feat.away_sp_days_rest = a_rest
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
    parser = argparse.ArgumentParser(description="Backfill pitcher rest days into nrfi_features.")
    parser.add_argument("--season", type=int, default=None, help="Limit to a specific season")
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing to DB")
    args = parser.parse_args()
    backfill(season=args.season, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
