"""
scripts/check_available_markets.py

One-off diagnostic script that lists every available market key per bookmaker
for today's first MLB game. Used to check whether NRFI/YRFI prop markets are
accessible on the current Odds API subscription.

Uses 2 API requests.

Usage:
    python scripts/check_available_markets.py
"""

import sys
import requests

sys.path.insert(0, ".")

from backend.core.config import get_settings

settings = get_settings()

# Step 1: Get today's events
print("Fetching today's MLB events...")
resp = requests.get(
    "https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
    params={"apiKey": settings.odds_api_key, "dateFormat": "iso"},
    timeout=10,
)
resp.raise_for_status()
print(f"Requests remaining: {resp.headers.get('x-requests-remaining')}\n")

events = resp.json()
if not events:
    print("No events found for today.")
    sys.exit(0)

event = events[0]
event_id = event["id"]
home = event["home_team"]
away = event["away_team"]
print(f"Checking all markets for: {away} @ {home}\n")

# Step 2: Fetch all available markets for that event
resp2 = requests.get(
    f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
    params={
        "apiKey": settings.odds_api_key,
        "regions": "us",
        "markets": "all",
        "oddsFormat": "american",
    },
    timeout=10,
)
resp2.raise_for_status()
print(f"Requests remaining after: {resp2.headers.get('x-requests-remaining')}\n")

data = resp2.json()
bookmakers = data.get("bookmakers", [])
if not bookmakers:
    print("No bookmakers returned.")
    sys.exit(0)

for bm in bookmakers:
    market_keys = [m["key"] for m in bm.get("markets", [])]
    print(f"{bm['title']:25s}  {market_keys}")
