"""
scripts/check_historical_odds.py

Checks whether The Odds API historical endpoint has NRFI (totals_1st_1_innings)
data for past MLB games.

Tests a sample date from each of the last 3 seasons to see what's available.

Uses ~6 API requests.

Usage:
    python scripts/check_historical_odds.py
"""

import sys
import time
import requests

sys.path.insert(0, ".")

from backend.core.config import get_settings

settings = get_settings()

_HISTORICAL_EVENTS_URL = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events"
_HISTORICAL_ODDS_URL   = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events/{event_id}/odds"

# Sample a mid-season date from each of the last 3 seasons
TEST_DATES = [
    "2025-06-15",
    "2024-06-15",
    "2023-06-15",
]


def check_date(date_str: str) -> None:
    print(f"\n{'='*60}")
    print(f"Checking {date_str}")
    print('='*60)

    # Step 1: Get events for this date
    resp = requests.get(
        _HISTORICAL_EVENTS_URL,
        params={
            "apiKey": settings.odds_api_key,
            "date": f"{date_str}T18:00:00Z",  # mid-afternoon UTC snapshot
            "dateFormat": "iso",
        },
        timeout=10,
    )
    print(f"Events status: {resp.status_code}  |  Remaining: {resp.headers.get('x-requests-remaining')}")

    if resp.status_code != 200:
        print(f"Error: {resp.json().get('message', resp.text)}")
        return

    data = resp.json()
    events = data.get("data", [])
    print(f"Events found: {len(events)}")

    if not events:
        return

    # Pick the first event
    event = events[0]
    event_id = event["id"]
    home = event["home_team"]
    away = event["away_team"]
    print(f"Sampling: {away} @ {home}  (id={event_id})")

    time.sleep(1)

    # Step 2: Fetch first-inning odds for that event
    resp2 = requests.get(
        _HISTORICAL_ODDS_URL.format(event_id=event_id),
        params={
            "apiKey": settings.odds_api_key,
            "date": f"{date_str}T18:00:00Z",
            "regions": "us",
            "markets": "totals_1st_1_innings",
            "oddsFormat": "american",
        },
        timeout=10,
    )
    print(f"Odds status:   {resp2.status_code}  |  Remaining: {resp2.headers.get('x-requests-remaining')}")

    if resp2.status_code != 200:
        print(f"Error: {resp2.json().get('message', resp2.text)}")
        return

    odds_data = resp2.json().get("data", {})
    bookmakers = odds_data.get("bookmakers", [])
    found = False
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] == "totals_1st_1_innings":
                found = True
                for outcome in market["outcomes"]:
                    print(f"  {bm['title']:25s}  {outcome['name']:6s}  point={outcome.get('point')}  odds={outcome['price']}")

    if not found:
        print("  totals_1st_1_innings: NOT available for this event")
        # Show what markets ARE available
        available = list({m["key"] for bm in bookmakers for m in bm.get("markets", [])})
        print(f"  Available markets: {available}")


for d in TEST_DATES:
    check_date(d)
    time.sleep(2)

print("\nDone.")
