"""
scripts/backfill_weather.py

Backfills weather features (temperature_f, wind_speed_mph, wind_out_mph, is_dome)
in nrfi_features for all existing rows using the Open-Meteo archive API.

Strategy: batch by park — one API call per park covering its full date range,
rather than one call per game. This keeps total API calls to ~30 (one per stadium).

For dome parks, is_dome is set to 1.0 and weather columns are left NULL.
For games with unknown parks, all weather columns are left NULL.

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_weather.py
    DATABASE_URL=postgresql://... python scripts/backfill_weather.py --season 2023
    DATABASE_URL=postgresql://... python scripts/backfill_weather.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict

from sqlalchemy import extract, text

sys.path.insert(0, ".")

from backend.data.fetch_weather import PARK_INFO, fetch_weather_for_park_daterange, _wind_out_component
from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def backfill(season: int | None = None, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        query = (
            db.query(NrfiFeatures.id, Game.park, Game.game_date)
            .join(Game, NrfiFeatures.game_id == Game.id)
            # Skip rows that already have weather data (temperature_f populated)
            # or are already marked as dome (is_dome = 1.0)
            .filter(
                NrfiFeatures.temperature_f.is_(None),
                (NrfiFeatures.is_dome.is_(None)) | (NrfiFeatures.is_dome != 1.0),
            )
        )
        if season:
            query = query.filter(extract("year", Game.game_date) == season)

        rows = query.all()
        logger.info("Found %d nrfi_features rows to backfill weather for.", len(rows))

        # Group by park so we can batch Open-Meteo calls
        # park → [(feat_id, game_date), ...]
        park_groups: dict[str | None, list[tuple[int, str]]] = defaultdict(list)
        for feat_id, park, game_date in rows:
            park_groups[park].append((feat_id, str(game_date)))

        total_updated = 0

        for park, park_rows in park_groups.items():
            if park is None:
                logger.warning("  %d rows have NULL park — weather will be NULL.", len(park_rows))
                continue

            info = PARK_INFO.get(park)
            if info is None:
                logger.warning("  Unknown park '%s' (%d rows) — weather will be NULL.", park, len(park_rows))
                continue

            if info["is_dome"]:
                logger.info("  %s: dome park — setting is_dome=1.0 for %d rows.", park, len(park_rows))
                for feat_id, _ in park_rows:
                    if not dry_run:
                        db.execute(
                            text("UPDATE nrfi_features SET is_dome = 1.0, temperature_f = NULL, wind_speed_mph = NULL, wind_out_mph = NULL WHERE id = :id"),
                            {"id": feat_id},
                        )
                total_updated += len(park_rows)
                continue

            dates = [d for _, d in park_rows]
            start_date, end_date = min(dates), max(dates)

            logger.info("  %s: fetching %s → %s (%d games)...", park, start_date, end_date, len(park_rows))
            hourly_data = fetch_weather_for_park_daterange(park, start_date, end_date)
            time.sleep(3)  # stay well under Open-Meteo rate limit

            if not hourly_data:
                logger.warning("  %s: no weather data returned — skipping.", park)
                continue

            for feat_id, date_str in park_rows:
                date_hours = hourly_data.get(date_str, {})
                row = date_hours.get(19) or date_hours.get(18) or date_hours.get(20)

                if row is None:
                    continue

                temp_f, wind_spd, wind_dir = row
                wind_out = (
                    _wind_out_component(wind_spd, wind_dir, info["outfield_dir"])
                    if wind_spd is not None and wind_dir is not None
                    else None
                )

                if not dry_run:
                    db.execute(
                        text("""
                            UPDATE nrfi_features
                            SET temperature_f   = :temp,
                                wind_speed_mph  = :wspd,
                                wind_out_mph    = :wout,
                                is_dome         = 0.0
                            WHERE id = :id
                        """),
                        {
                            "temp": round(temp_f, 1) if temp_f is not None else None,
                            "wspd": round(wind_spd, 1) if wind_spd is not None else None,
                            "wout": wind_out,
                            "id": feat_id,
                        },
                    )
                total_updated += 1

            if not dry_run:
                db.commit()
            logger.info("  %s: done.", park)

        if dry_run:
            logger.info("[dry-run] Would update %d rows.", total_updated)
        else:
            logger.info("Done. Updated weather for %d rows.", total_updated)

    except Exception:
        db.rollback()
        logger.exception("Backfill failed — rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill weather features in nrfi_features.")
    parser.add_argument("--season", type=int, default=None, help="Only backfill a specific season.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(season=args.season, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
