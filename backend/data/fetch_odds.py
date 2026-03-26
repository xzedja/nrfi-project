"""
backend/data/fetch_odds.py

Fetches MLB moneyline and totals odds from The Odds API, stores them in
the Odds table, and updates NrfiFeatures.p_nrfi_market with an estimated
NRFI probability derived from the game total.

API key: set ODDS_API_KEY environment variable.
Docs:    https://the-odds-api.com/liveapi/guides/v4/

NRFI approximation:
    The Odds API does not expose a dedicated NRFI market on the free tier.
    We approximate P(NRFI) from the game total using a calibrated Poisson model:

        λ = (total / 18) × 0.74   ← first-inning run rate per half-inning
        P(NRFI) = e^(−2λ)

    The 0.74 factor is calibrated so that an average total of 8.5 produces
    P(NRFI) ≈ 0.50, matching our observed historical rate.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.db.models import Game, NrfiFeatures, Odds

logger = logging.getLogger(__name__)

_ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/"
_PREFERRED_BOOKMAKER = "draftkings"
_REQUEST_TIMEOUT = 10

# Map The Odds API full team names → Statcast abbreviations used in our DB
_TEAM_NAME_TO_ABBREV: dict[str, str] = {
    "Arizona Diamondbacks": "AZ",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Cleveland Indians": "CLE",      # legacy name
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Oakland Athletics": "ATH",
    "Sacramento Athletics": "ATH",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


# ---------------------------------------------------------------------------
# Odds math helpers
# ---------------------------------------------------------------------------

def american_to_implied(odds: int) -> float:
    """
    Convert American odds to raw implied probability (includes bookmaker vig).

    Examples:
        -110 → 0.524   (favorite)
        +110 → 0.476   (underdog)
    """
    if odds < 0:
        return (-odds) / (-odds + 100)
    return 100 / (odds + 100)


def remove_vig(p1: float, p2: float) -> tuple[float, float]:
    """
    Remove bookmaker vig from a two-outcome market by normalising the
    implied probabilities to sum to 1.
    """
    total = p1 + p2
    return p1 / total, p2 / total


def estimate_p_nrfi_from_total(total: float) -> float:
    """
    Estimate P(NRFI) from the game total using a calibrated Poisson model.

    Calibration: at total = 8.5, P(NRFI) ≈ 0.50 (matches historical average).
    """
    lambda_per_half = (total / 18) * 0.74
    return math.exp(-2 * lambda_per_half)


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------

def _fetch_raw_odds(date_str: str) -> list[dict[str, Any]]:
    """Call The Odds API and return raw game odds for the given date."""
    settings = get_settings()
    params = {
        "apiKey": settings.odds_api_key,
        "regions": "us",
        "markets": "h2h,totals",
        "dateFormat": "iso",
        "oddsFormat": "american",
        # commenceTime is UTC. US games on date_str can start as late as
        # ~03:00Z the following day (10 PM ET / 7 PM PT). Use +1 day noon UTC
        # as the upper bound so we catch all same-date games without pulling
        # in the next calendar day's slate.
        "commenceTimeFrom": f"{date_str}T00:00:00Z",
        "commenceTimeTo": f"{(date.fromisoformat(date_str) + timedelta(days=1)).isoformat()}T12:00:00Z",
    }
    try:
        resp = requests.get(_ODDS_API_BASE, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.info("Odds API response OK. Requests remaining: %s", remaining)
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Failed to fetch odds: %s", exc)
        return []


def _extract_best_markets(game: dict, preferred: str) -> dict[str, Any]:
    """
    Build a single merged market dict using the best available data across bookmakers.
    Uses the preferred bookmaker for moneylines, but falls back to any bookmaker
    that has a total if the preferred one doesn't.
    """
    bookmakers = game.get("bookmakers", [])
    if not bookmakers:
        return {}

    # Pick preferred bookmaker, fall back to first
    pref = next((b for b in bookmakers if b["key"] == preferred), bookmakers[0])
    merged = _parse_markets(pref)
    source = pref["key"]

    # If total is missing from preferred, scan other bookmakers for it
    if merged.get("total") is None:
        for bm in bookmakers:
            if bm["key"] == pref["key"]:
                continue
            other = _parse_markets(bm)
            if other.get("total") is not None:
                merged["total"] = other["total"]
                merged["total_over_odds"] = other["total_over_odds"]
                merged["total_under_odds"] = other["total_under_odds"]
                logger.debug("Total sourced from %s instead of %s", bm["key"], source)
                break

    merged["_source"] = source
    return merged


def _parse_markets(bookmaker: dict) -> dict[str, Any]:
    """Extract h2h and totals data from a bookmaker entry."""
    result: dict[str, Any] = {
        "home_ml": None,
        "away_ml": None,
        "total": None,
        "total_over_odds": None,
        "total_under_odds": None,
    }
    for market in bookmaker.get("markets", []):
        if market["key"] == "h2h":
            for outcome in market["outcomes"]:
                # The Odds API h2h uses full team names as outcome names
                result[f"_h2h_{outcome['name']}"] = outcome["price"]
        elif market["key"] == "totals":
            for outcome in market["outcomes"]:
                if outcome["name"] == "Over":
                    result["total"] = outcome.get("point")
                    result["total_over_odds"] = outcome["price"]
                elif outcome["name"] == "Under":
                    result["total_under_odds"] = outcome["price"]
    return result


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def fetch_and_store_odds(date_str: str | None = None, db: Session | None = None) -> int:
    """
    Fetch odds from The Odds API for the given date, store in the Odds table,
    and update NrfiFeatures.p_nrfi_market for each matched game.

    Returns the number of games with odds successfully stored.
    """
    from backend.db.session import SessionLocal

    target = date_str or str(date.today())
    logger.info("Fetching odds for %s", target)

    raw = _fetch_raw_odds(target)
    if not raw:
        logger.info("No odds returned for %s.", target)
        return 0

    close_db = db is None
    if db is None:
        db = SessionLocal()

    matched = 0
    try:
        for game_odds in raw:
            home_full = game_odds.get("home_team", "")
            away_full = game_odds.get("away_team", "")

            home_abbrev = _TEAM_NAME_TO_ABBREV.get(home_full)
            away_abbrev = _TEAM_NAME_TO_ABBREV.get(away_full)

            if not home_abbrev or not away_abbrev:
                logger.warning(
                    "Unknown team name(s): home=%r away=%r — skipping.", home_full, away_full
                )
                continue

            # Use ±1 day window to handle UTC vs local date mismatches
            # (e.g. Tokyo Series games cross midnight UTC relative to US game date)
            target_date = date.fromisoformat(target)
            game = (
                db.query(Game)
                .filter(
                    Game.game_date.between(
                        target_date - timedelta(days=1),
                        target_date + timedelta(days=1),
                    ),
                    Game.home_team == home_abbrev,
                    Game.away_team == away_abbrev,
                )
                .first()
            )
            if game is None:
                logger.debug(
                    "No DB game found for %s @ %s on %s — skipping.",
                    away_abbrev, home_abbrev, target,
                )
                continue

            markets = _extract_best_markets(game_odds, _PREFERRED_BOOKMAKER)
            if not markets:
                continue

            # Map h2h outcome names (full names) to home/away ml
            home_ml = markets.pop(f"_h2h_{home_full}", None)
            away_ml = markets.pop(f"_h2h_{away_full}", None)
            source = markets.pop("_source", _PREFERRED_BOOKMAKER)
            # Clean up any leftover _h2h_ keys
            for k in [k for k in markets if k.startswith("_h2h_")]:
                markets.pop(k)

            # Sanity-check the total — alternate/half-game lines slip in from
            # fallback bookmakers (e.g. 3.5 = first-5 total, 11.5 = alt line).
            # MLB full-game totals are always in the 5–15 range.
            raw_total = markets["total"]
            if raw_total is not None and not (5.0 <= raw_total <= 15.0):
                logger.warning(
                    "Skipping implausible total %.1f for %s @ %s — likely alternate market.",
                    raw_total, away_abbrev, home_abbrev,
                )
                markets["total"] = None
                markets["total_over_odds"] = None
                markets["total_under_odds"] = None

            # Upsert: update existing odds row rather than inserting a duplicate
            odds_row = db.query(Odds).filter_by(game_id=game.id, source=source).first()
            if odds_row is None:
                odds_row = Odds(game_id=game.id, source=source, market="total")
                db.add(odds_row)
            odds_row.home_ml = home_ml
            odds_row.away_ml = away_ml
            odds_row.total = markets["total"]
            odds_row.total_over_odds = markets["total_over_odds"]
            odds_row.total_under_odds = markets["total_under_odds"]
            odds_row.fetched_at = datetime.now(timezone.utc)

            # Update p_nrfi_market on the features row if we have a total
            if markets["total"] is not None:
                p_market = estimate_p_nrfi_from_total(markets["total"])
                feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()
                if feat is not None:
                    feat.p_nrfi_market = round(p_market, 4)

            matched += 1

        db.commit()
        logger.info("Odds stored for %d / %d games.", matched, len(raw))

    except Exception:
        db.rollback()
        logger.exception("Error storing odds — rolled back.")
        raise
    finally:
        if close_db:
            db.close()

    return matched
