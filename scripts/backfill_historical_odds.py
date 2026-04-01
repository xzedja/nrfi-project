"""
scripts/backfill_historical_odds.py

Hybrid backfill of p_nrfi_market for historical games:

  RECENT games (last N game days, default 100):
    - Two-step fetch from The Odds API:
        1. GET /events?date={snapshot}  → event IDs
        2. GET /events/{id}/odds?date={snapshot}&markets=totals_1st_1_innings
    - Blended probability: 0.80 * p_actual + 0.20 * p_poisson
      (actual odds dominate; Poisson acts as sanity-check anchor)
    - Cost: ~1 + 10 credits per event, ~151 credits/day

  OLDER games (beyond the recent window):
    - GET /odds-history?markets=totals  → game total
    - Poisson approximation: p_nrfi = exp(-2 * (total/18) * 0.74)
    - Cost: ~1 credit/day

Credit estimate (correct /historical/ endpoint costs 10 credits/call):
  - 100 recent days:  ~15,100 credits  (1 events + 15×10 per-event)
  - ~500 older days:  ~5,000 credits   (10 credits/day for totals)
  - Total:            ~20,100 credits

Blend weight rationale (80/20):
  Actual NRFI lines are the market clearing price and are ~4x more
  informative than Poisson. The 20% Poisson component acts as a
  sanity check against stale or anomalous noon-ET snapshots.

Usage:
    python scripts/backfill_historical_odds.py
    python scripts/backfill_historical_odds.py --recent-days 100
    python scripts/backfill_historical_odds.py --start 2023-05-03 --end 2024-12-31
    python scripts/backfill_historical_odds.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
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
    estimate_p_nrfi_from_total,
    remove_vig,
)
from backend.db.models import Game, NrfiFeatures, Odds
from backend.db.session import SessionLocal

_HISTORY_URL     = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds"
_EVENTS_URL      = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events"
_EVENT_ODDS_URL  = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events/{event_id}/odds"
_REQUEST_TIMEOUT = 15
_DELAY_SECS      = 0.5

# Blend weights: actual NRFI line vs Poisson approximation
_WEIGHT_ACTUAL  = 0.80
_WEIGHT_POISSON = 0.20

# Sanity range for game totals
_TOTAL_MIN = 5.0
_TOTAL_MAX = 15.0

_BOOKMAKER_PREF = ["draftkings", "fanduel", "caesars", "betmgm", "betonline", "bovada"]


# ---------------------------------------------------------------------------
# Poisson path — batch /odds-history with standard totals market
# ---------------------------------------------------------------------------

def _fetch_historical_totals(date_str: str) -> list[dict[str, Any]]:
    """Fetch game totals from /odds-history at noon ET (17:00 UTC)."""
    settings = get_settings()
    try:
        resp = requests.get(
            _HISTORY_URL,
            params={
                "apiKey": settings.odds_api_key,
                "regions": "us",
                "markets": "totals",
                "oddsFormat": "american",
                "date": f"{date_str}T17:00:00Z",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used      = resp.headers.get("x-requests-used", "?")
        logger.info("  [poisson] %s — used: %s  remaining: %s", date_str, used, remaining)
        body = resp.json()
        return body.get("data", body) if isinstance(body, dict) else body
    except requests.RequestException as exc:
        logger.warning("  [poisson] %s fetch failed: %s", date_str, exc)
        return []


def _extract_total(game_data: dict) -> float | None:
    """Return the preferred bookmaker's game total, or None."""
    bm_totals: dict[str, float] = {}
    for bm in game_data.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "totals":
                continue
            for outcome in market.get("outcomes", []):
                if outcome["name"] == "Over":
                    val = outcome.get("point")
                    if val is not None and _TOTAL_MIN <= float(val) <= _TOTAL_MAX:
                        bm_totals[bm["key"]] = float(val)
    if not bm_totals:
        return None
    for key in _BOOKMAKER_PREF:
        if key in bm_totals:
            return bm_totals[key]
    return next(iter(bm_totals.values()))


# ---------------------------------------------------------------------------
# Actual NRFI odds path — event-specific historical endpoint
# ---------------------------------------------------------------------------

def _fetch_event_ids_at_snapshot(date_str: str) -> list[dict[str, Any]]:
    """
    Fetch historical event list at the noon-ET snapshot.
    Uses the date parameter on /events (historical events endpoint).
    """
    settings = get_settings()
    try:
        resp = requests.get(
            _EVENTS_URL,
            params={
                "apiKey": settings.odds_api_key,
                "date": f"{date_str}T17:00:00Z",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used      = resp.headers.get("x-requests-used", "?")
        body = resp.json()
        events = body.get("data", body) if isinstance(body, dict) else body
        logger.info(
            "  [actual] %s — %d events  used: %s  remaining: %s",
            date_str, len(events), used, remaining,
        )
        return events if isinstance(events, list) else []
    except requests.RequestException as exc:
        logger.warning("  [actual] %s events fetch failed: %s", date_str, exc)
        return []


def _fetch_event_nrfi_odds(event_id: str, date_str: str) -> dict[str, Any] | None:
    """Fetch period market odds for one event at the noon-ET snapshot."""
    settings = get_settings()
    try:
        resp = requests.get(
            _EVENT_ODDS_URL.format(event_id=event_id),
            params={
                "apiKey": settings.odds_api_key,
                "regions": "us",
                "markets": "totals_1st_1_innings",
                "oddsFormat": "american",
                "date": f"{date_str}T17:00:00Z",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code in (404, 422):
            return None
        resp.raise_for_status()
        body = resp.json()
        # Historical endpoint wraps game in {"data": {...}}
        return body.get("data", body) if isinstance(body, dict) and "data" in body else body
    except requests.RequestException as exc:
        logger.debug("  [actual] event %s odds failed: %s", event_id, exc)
        return None


def _parse_nrfi_odds(event_data: dict) -> dict[str, int | None]:
    """Extract Over/Under American odds from preferred bookmaker."""
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


# ---------------------------------------------------------------------------
# Shared game matching
# ---------------------------------------------------------------------------

def _match_game(
    home_full: str,
    away_full: str,
    db_games: dict[tuple[str, str], Game],
) -> Game | None:
    home_abbrev = _TEAM_NAME_TO_ABBREV.get(home_full)
    away_abbrev = _TEAM_NAME_TO_ABBREV.get(away_full)
    if home_abbrev and away_abbrev:
        game = db_games.get((home_abbrev, away_abbrev))
        if game:
            return game
    for full, abbrev in _TEAM_NAME_TO_ABBREV.items():
        if full in home_full or home_full in full:
            home_abbrev = abbrev
        if full in away_full or away_full in full:
            away_abbrev = abbrev
    return db_games.get((home_abbrev, away_abbrev)) if home_abbrev and away_abbrev else None


# ---------------------------------------------------------------------------
# Per-date processors
# ---------------------------------------------------------------------------

def _db_games_for_date(date_str: str, db) -> dict[tuple[str, str], Game]:
    games = db.query(Game).filter(Game.game_date == date_str).all()
    return {(g.home_team, g.away_team): g for g in games}


def process_date_actual(date_str: str, db, dry_run: bool = False) -> int:
    """
    Fetch real NRFI odds for a date and store blended p_nrfi_market.
    Blend = 0.80 * p_actual + 0.20 * p_poisson.
    """
    db_games = _db_games_for_date(date_str, db)
    if not db_games:
        return 0

    if dry_run:
        logger.info("  [dry-run/actual] %s — %d games", date_str, len(db_games))
        return 0

    events = _fetch_event_ids_at_snapshot(date_str)
    if not events:
        return 0

    updated = 0
    for event in events:
        event_id  = event.get("id")
        home_full = event.get("home_team", "")
        away_full = event.get("away_team", "")

        game = _match_game(home_full, away_full, db_games)
        if game is None:
            continue

        time.sleep(_DELAY_SECS)
        event_data = _fetch_event_nrfi_odds(event_id, date_str)
        if event_data is None:
            continue

        nrfi = _parse_nrfi_odds(event_data)
        over_odds  = nrfi["over_odds"]
        under_odds = nrfi["under_odds"]
        if over_odds is None or under_odds is None:
            continue

        # Derive actual vig-removed probability
        p_yrfi_raw = american_to_implied(over_odds)
        p_nrfi_raw = american_to_implied(under_odds)
        _, p_actual = remove_vig(p_yrfi_raw, p_nrfi_raw)

        # Poisson component for sanity anchoring
        # We need the game total; approximate from odds-history separately
        # For the blend, derive Poisson from a standard total if available,
        # else use p_actual only.
        p_poisson = None
        # We'll fill this in after the totals fetch; for now store actual-only
        # and update if totals data is available (handled in process_date_hybrid).

        # Store actual odds in Odds table
        odds_row = db.query(Odds).filter_by(game_id=game.id, source="historical_odds_api").first()
        if odds_row is None:
            odds_row = Odds(game_id=game.id, source="historical_odds_api", market="nrfi")
            db.add(odds_row)
        odds_row.first_inn_over_odds  = over_odds
        odds_row.first_inn_under_odds = under_odds

        # Store p_nrfi_market (blending handled in hybrid processor)
        feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()
        if feat is not None and feat.p_nrfi_market is None:
            feat.p_nrfi_market = round(p_actual, 4)  # placeholder; hybrid will blend

        updated += 1

    db.commit()
    return updated


def process_date_hybrid(date_str: str, db, use_actual: bool, dry_run: bool = False, overwrite: bool = False) -> int:
    """
    Single entry point for both paths.

    use_actual=True  → fetch real NRFI odds + blend with Poisson
    use_actual=False → Poisson only from game totals
    """
    db_games = _db_games_for_date(date_str, db)
    if not db_games:
        return 0

    if dry_run:
        mode = "actual+blend" if use_actual else "poisson"
        logger.info("  [dry-run/%s] %s — %d games", mode, date_str, len(db_games))
        return 0

    # Always fetch game totals for Poisson component
    totals_data = _fetch_historical_totals(date_str)
    total_by_game: dict[tuple[str, str], float] = {}
    for gd in totals_data:
        h = gd.get("home_team", "")
        a = gd.get("away_team", "")
        total = _extract_total(gd)
        if total is not None:
            habbr = _TEAM_NAME_TO_ABBREV.get(h)
            aabbr = _TEAM_NAME_TO_ABBREV.get(a)
            if habbr and aabbr:
                total_by_game[(habbr, aabbr)] = total

    actual_by_game: dict[tuple[str, str], float] = {}
    actual_odds_by_game: dict[tuple[str, str], tuple[int, int]] = {}

    if use_actual:
        events = _fetch_event_ids_at_snapshot(date_str)
        for event in events:
            event_id  = event.get("id")
            home_full = event.get("home_team", "")
            away_full = event.get("away_team", "")

            game = _match_game(home_full, away_full, db_games)
            if game is None:
                continue

            time.sleep(_DELAY_SECS)
            event_data = _fetch_event_nrfi_odds(event_id, date_str)
            if event_data is None:
                continue

            nrfi = _parse_nrfi_odds(event_data)
            if nrfi["over_odds"] is None or nrfi["under_odds"] is None:
                continue

            p_yrfi_raw = american_to_implied(nrfi["over_odds"])
            p_nrfi_raw = american_to_implied(nrfi["under_odds"])
            _, p_actual = remove_vig(p_yrfi_raw, p_nrfi_raw)

            key = (game.home_team, game.away_team)
            actual_by_game[key]     = p_actual
            actual_odds_by_game[key] = (nrfi["over_odds"], nrfi["under_odds"])

    updated = 0
    for (home_abbr, away_abbr), game in db_games.items():
        feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()
        if feat is None:
            continue
        if feat.p_nrfi_market is not None and not overwrite:
            continue  # skip already-populated rows unless --overwrite

        key     = (home_abbr, away_abbr)
        p_act   = actual_by_game.get(key)
        total   = total_by_game.get(key)
        p_pois  = estimate_p_nrfi_from_total(total) if total is not None else None

        if p_act is not None and p_pois is not None:
            # Blend: actual dominates, Poisson anchors
            p_market = _WEIGHT_ACTUAL * p_act + _WEIGHT_POISSON * p_pois
            source   = "blended"
        elif p_act is not None:
            p_market = p_act
            source   = "actual"
        elif p_pois is not None:
            p_market = p_pois
            source   = "poisson"
        else:
            continue

        feat.p_nrfi_market = round(p_market, 4)

        # Store raw odds in Odds table if we have them
        if key in actual_odds_by_game:
            over_odds, under_odds = actual_odds_by_game[key]
            odds_row = db.query(Odds).filter_by(game_id=game.id, source="historical_odds_api").first()
            if odds_row is None:
                odds_row = Odds(game_id=game.id, source="historical_odds_api", market="nrfi")
                db.add(odds_row)
            odds_row.first_inn_over_odds  = over_odds
            odds_row.first_inn_under_odds = under_odds

        logger.debug("  %s @ %s  [%s]  p_market=%.4f", away_abbr, home_abbr, source, p_market)
        updated += 1

    db.commit()
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Hybrid historical odds backfill: actual NRFI lines (blended) for recent "
            "game days, Poisson approximation from game totals for older dates."
        )
    )
    parser.add_argument("--start", default="2023-05-03",
                        help="Start date YYYY-MM-DD (default: 2023-05-03)")
    parser.add_argument("--end", default=str(date.today()),
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--recent-days", type=int, default=100,
                        help="Number of most recent game days to use actual NRFI odds (default: 100)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without making API calls")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing p_nrfi_market values (re-fetch actual odds)")
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

    # Split: last N dates use actual NRFI odds; older dates use Poisson
    cutoff_idx   = max(0, len(game_dates) - args.recent_days)
    poisson_dates = game_dates[:cutoff_idx]
    actual_dates  = game_dates[cutoff_idx:]

    logger.info(
        "Backfill plan: %s → %s  (%d total game dates)",
        args.start, args.end, len(game_dates),
    )
    logger.info(
        "  Poisson path  : %d dates  (~%d credits)",
        len(poisson_dates), len(poisson_dates),
    )
    logger.info(
        "  Actual+blend  : %d dates  (~%d credits)",
        len(actual_dates), len(actual_dates) * 151,
    )
    logger.info(
        "  Blend weights : %.0f%% actual + %.0f%% Poisson",
        _WEIGHT_ACTUAL * 100, _WEIGHT_POISSON * 100,
    )
    if args.dry_run:
        logger.info("Dry run — no API calls.")

    total_updated = 0
    db = SessionLocal()
    try:
        # Poisson path (cheap — older dates)
        logger.info("--- Poisson path (%d dates) ---", len(poisson_dates))
        for i, date_str in enumerate(poisson_dates):
            updated = process_date_hybrid(date_str, db, use_actual=False, dry_run=args.dry_run, overwrite=args.overwrite)
            total_updated += updated
            if updated:
                logger.info("  %s — updated %d games", date_str, updated)
            if not args.dry_run and i < len(poisson_dates) - 1:
                time.sleep(0.5)

        # Actual odds path (recent dates)
        logger.info("--- Actual+blend path (%d dates) ---", len(actual_dates))
        for date_str in actual_dates:
            updated = process_date_hybrid(date_str, db, use_actual=True, dry_run=args.dry_run, overwrite=args.overwrite)
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
