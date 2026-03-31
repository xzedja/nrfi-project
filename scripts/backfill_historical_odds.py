"""
scripts/backfill_historical_odds.py

Backfills NRFI/YRFI first-inning odds for historical games using The Odds API.

The batch /odds-history endpoint does NOT support period markets like
totals_1st_1_innings. We use a two-step approach instead:
  1. GET /events  — list event IDs for the game date (1 credit/date)
  2. GET /events/{id}/odds?date=snapshot  — period market odds per event

Historical period market data is available from May 3, 2023 onwards.
Queries at 17:00 UTC (noon ET) each game day to capture pre-game lines.

Credit cost: ~1 (events list) + N per game day, where N = games that day.
With ~15 games/day × ~600 dates = ~9,600 total credits (plus events calls).
Credit counter is printed after each date.

Usage:
    python scripts/backfill_historical_odds.py
    python scripts/backfill_historical_odds.py --start 2023-05-03 --end 2024-12-31
    python scripts/backfill_historical_odds.py --dry-run   # shows dates, no API calls
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.core.config import get_settings
from backend.data.fetch_odds import (
    _FIRST_INN_BOOKMAKER_PREFERENCE,
    _TEAM_NAME_TO_ABBREV,
    american_to_implied,
    remove_vig,
)
from backend.db.models import Game, NrfiFeatures, Odds
from backend.db.session import SessionLocal

_EVENTS_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events"
_EVENT_ODDS_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds"
_REQUEST_TIMEOUT = 15
_DELAY_SECS = 0.5  # polite delay between per-event requests


def _fetch_event_ids_for_date(date_str: str) -> list[dict[str, Any]]:
    """
    Fetch The Odds API event list for games commencing on the given date.
    Returns list of {id, home_team, away_team, commence_time} dicts.
    """
    settings = get_settings()
    next_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            _EVENTS_URL,
            params={
                "apiKey": settings.odds_api_key,
                "commenceTimeFrom": f"{date_str}T00:00:00Z",
                "commenceTimeTo": f"{next_date}T12:00:00Z",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        events = resp.json()
        logger.info(
            "  %s — %d events found  [used: %s  remaining: %s]",
            date_str, len(events), used, remaining,
        )
        return events
    except requests.RequestException as exc:
        logger.warning("  Failed to fetch events for %s: %s", date_str, exc)
        return []


def _fetch_event_nrfi_odds(event_id: str, date_str: str) -> dict[str, Any] | None:
    """
    Fetch first-inning odds for a single event at the noon-ET (17:00 UTC) snapshot.
    Returns the event dict with bookmakers, or None if unavailable.
    """
    settings = get_settings()
    snapshot_ts = f"{date_str}T17:00:00Z"

    try:
        resp = requests.get(
            _EVENT_ODDS_URL.format(event_id=event_id),
            params={
                "apiKey": settings.odds_api_key,
                "regions": "us",
                "markets": "totals_1st_1_innings",
                "oddsFormat": "american",
                "date": snapshot_ts,
            },
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code in (404, 422):
            # Market not available for this event / snapshot
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.debug("  Event %s odds fetch failed: %s", event_id, exc)
        return None


def _parse_nrfi_from_event(event_data: dict) -> dict[str, int | None]:
    """
    Extract NRFI (Under 0.5) and YRFI (Over 0.5) American odds from an event dict.
    Uses preferred bookmaker order, falls back to any available.
    """
    bm_odds: dict[str, dict] = {}
    for bm in event_data.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "totals_1st_1_innings":
                continue
            over = under = None
            for outcome in market.get("outcomes", []):
                if outcome["name"] == "Over":
                    over = outcome.get("price")
                elif outcome["name"] == "Under":
                    under = outcome.get("price")
            if over is not None and under is not None:
                bm_odds[bm["key"]] = {"over": int(over), "under": int(under)}

    if not bm_odds:
        return {"over_odds": None, "under_odds": None}

    for key in _FIRST_INN_BOOKMAKER_PREFERENCE:
        if key in bm_odds:
            return {"over_odds": bm_odds[key]["over"], "under_odds": bm_odds[key]["under"]}

    best = next(iter(bm_odds.values()))
    return {"over_odds": best["over"], "under_odds": best["under"]}


def _match_game(
    home_full: str,
    away_full: str,
    db_games: dict[tuple[str, str], Game],
) -> Game | None:
    """
    Match an Odds API game (full team names) to a DB Game row (abbreviations).
    Tries exact match first, then partial substring match.
    """
    home_abbrev = _TEAM_NAME_TO_ABBREV.get(home_full)
    away_abbrev = _TEAM_NAME_TO_ABBREV.get(away_full)

    if home_abbrev and away_abbrev:
        game = db_games.get((home_abbrev, away_abbrev))
        if game:
            return game

    # Fuzzy fallback
    for full, abbrev in _TEAM_NAME_TO_ABBREV.items():
        if full in home_full or home_full in full:
            home_abbrev = abbrev
        if full in away_full or away_full in full:
            away_abbrev = abbrev

    return db_games.get((home_abbrev, away_abbrev)) if home_abbrev and away_abbrev else None


def process_date(date_str: str, db, dry_run: bool = False) -> int:
    """
    Fetch and store historical NRFI odds for a single game date.
    Returns number of games updated.
    """
    games = db.query(Game).filter(Game.game_date == date_str).all()
    if not games:
        return 0

    db_games: dict[tuple[str, str], Game] = {
        (g.home_team, g.away_team): g for g in games
    }

    if dry_run:
        logger.info("  [dry-run] %s — %d games in DB", date_str, len(games))
        return 0

    # Step 1: get event IDs for this date
    events = _fetch_event_ids_for_date(date_str)
    if not events:
        return 0

    updated = 0
    for event in events:
        event_id = event.get("id")
        home_full = event.get("home_team", "")
        away_full = event.get("away_team", "")

        game = _match_game(home_full, away_full, db_games)
        if game is None:
            logger.debug("  No DB match for %s @ %s on %s", away_full, home_full, date_str)
            continue

        # Step 2: fetch period market odds at the historical snapshot
        time.sleep(_DELAY_SECS)
        event_data = _fetch_event_nrfi_odds(event_id, date_str)
        if event_data is None:
            continue

        nrfi = _parse_nrfi_from_event(event_data)
        over_odds = nrfi["over_odds"]
        under_odds = nrfi["under_odds"]

        if over_odds is None and under_odds is None:
            continue

        # Upsert Odds row
        odds_row = db.query(Odds).filter_by(game_id=game.id, source="historical_odds_api").first()
        if odds_row is None:
            odds_row = Odds(game_id=game.id, source="historical_odds_api", market="nrfi")
            db.add(odds_row)

        odds_row.first_inn_over_odds  = over_odds
        odds_row.first_inn_under_odds = under_odds

        # Update nrfi_features.p_nrfi_market if currently NULL
        if over_odds and under_odds:
            feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()
            if feat is not None and feat.p_nrfi_market is None:
                p_yrfi_raw = american_to_implied(over_odds)
                p_nrfi_raw = american_to_implied(under_odds)
                _, p_market = remove_vig(p_yrfi_raw, p_nrfi_raw)
                feat.p_nrfi_market = round(p_market, 4)

        updated += 1

    db.commit()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historical NRFI odds from The Odds API (two-step: events → per-event odds)."
    )
    parser.add_argument(
        "--start", default="2023-05-03",
        help="Start date YYYY-MM-DD (default: 2023-05-03, first available)"
    )
    parser.add_argument(
        "--end", default=str(date.today()),
        help="End date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List dates without making API calls"
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)

    db = SessionLocal()
    try:
        all_games = (
            db.query(Game.game_date)
            .filter(Game.game_date >= start, Game.game_date <= end)
            .distinct()
            .order_by(Game.game_date)
            .all()
        )
        game_dates = [str(row[0]) for row in all_games]
    finally:
        db.close()

    logger.info(
        "Backfilling historical NRFI odds: %s → %s  (%d game dates)",
        args.start, args.end, len(game_dates)
    )

    if args.dry_run:
        logger.info("Dry run — no API calls will be made.")

    total_updated = 0
    db = SessionLocal()
    try:
        for date_str in game_dates:
            updated = process_date(date_str, db, dry_run=args.dry_run)
            total_updated += updated
            if updated:
                logger.info("  %s — updated %d games", date_str, updated)

        logger.info("Done. Total games updated: %d", total_updated)

    except Exception:
        db.rollback()
        logger.exception("Backfill failed.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
