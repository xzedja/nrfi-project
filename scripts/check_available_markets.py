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

from datetime import timezone
import datetime as dt

now = dt.datetime.now(timezone.utc)

# Pick the first game that hasn't started yet
future_events = [
    e for e in events
    if dt.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) > now
]

if not future_events:
    print("No upcoming games found — all today's games may have already started.")
    sys.exit(0)

event = future_events[0]
event_id = event["id"]
home = event["home_team"]
away = event["away_team"]
commence = event["commence_time"]
print(f"Checking markets for: {away} @ {home}  (starts {commence})\n")

# Step 2: Try inning-specific markets, both with regions=us and bookmakers=fanduel
from datetime import date, timedelta

target = str(date.today())
time_params = {
    "apiKey": settings.odds_api_key,
    "oddsFormat": "american",
    "dateFormat": "iso",
    "commenceTimeFrom": f"{target}T00:00:00Z",
    "commenceTimeTo": f"{(date.fromisoformat(target) + timedelta(days=1)).isoformat()}T12:00:00Z",
}

MARKETS_TO_PROBE = [
    "h2h_1st_1_innings",
    "h2h_1st_5_innings",
    "totals_1st_1_innings",
    "totals_1st_3_innings",
    "totals_1st_5_innings",
    "spreads_1st_1_innings",
    "nrfi",
    "yrfi",
    "team_totals",
    "alternate_totals",
]

import time
print("Fetching totals_1st_1_innings (waiting 5s to avoid rate limit)...")
time.sleep(5)

r = requests.get(
    "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
    params={**time_params, "markets": "totals_1st_1_innings", "regions": "us"},
    timeout=10,
)
print(f"Status: {r.status_code}  |  Requests remaining: {r.headers.get('x-requests-remaining')}\n")

if r.status_code != 200:
    print(f"Error: {r.text}")
    sys.exit(1)

games = r.json()
print(f"{len(games)} game(s) returned\n")

for game in games:
    home = game["home_team"]
    away = game["away_team"]
    print(f"{away} @ {home}")
    for bm in game.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] == "totals_1st_1_innings":
                for outcome in market["outcomes"]:
                    print(f"  {bm['title']:20s}  {outcome['name']:6s}  {outcome.get('point')}  {outcome['price']}")
    print()

