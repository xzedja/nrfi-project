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

# Step 2: Try inning-specific markets on the regular odds endpoint
# (event-specific endpoint may require a higher tier)
from datetime import date, timedelta

target = str(date.today())
MARKETS_TO_PROBE = [
    "h2h_1st_5_innings",
    "team_totals",
    "alternate_totals",
    "nrfi",
    "yrfi",
    "h2h_1st_1_innings",
    "totals_1st_1_innings",
]

for market in MARKETS_TO_PROBE:
    resp2 = requests.get(
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
        params={
            "apiKey": settings.odds_api_key,
            "regions": "us",
            "markets": market,
            "oddsFormat": "american",
            "dateFormat": "iso",
            "commenceTimeFrom": f"{target}T00:00:00Z",
            "commenceTimeTo": f"{(date.fromisoformat(target) + timedelta(days=1)).isoformat()}T12:00:00Z",
        },
        timeout=10,
    )
    remaining = resp2.headers.get("x-requests-remaining", "?")
    if resp2.status_code == 422:
        print(f"  {market:35s} — 422 (not supported on this tier)")
    elif resp2.status_code != 200:
        print(f"  {market:35s} — {resp2.status_code}")
    else:
        games = resp2.json()
        has_data = any(
            any(m["key"] == market for bm in g.get("bookmakers", []) for m in bm.get("markets", []))
            for g in games
        )
        print(f"  {market:35s} — OK ({remaining} requests left, data={'YES' if has_data else 'no'})")

