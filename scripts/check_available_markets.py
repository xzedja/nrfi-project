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

print(f"{'Market':<35}  {'regions=us':<20}  bookmakers=fanduel")
print("-" * 80)

for market in MARKETS_TO_PROBE:
    results = []
    for label, extra in [("regions=us", {"regions": "us"}), ("bookmakers=fanduel", {"bookmakers": "fanduel"})]:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
            params={**time_params, "markets": market, **extra},
            timeout=10,
        )
        if r.status_code == 422:
            results.append("422")
        elif r.status_code != 200:
            results.append(str(r.status_code))
        else:
            games = r.json()
            has_data = any(
                any(m["key"] == market for bm in g.get("bookmakers", []) for m in bm.get("markets", []))
                for g in games
            )
            results.append(f"OK ({'data' if has_data else 'empty'})")

    print(f"  {market:<35}  {results[0]:<20}  {results[1]}")

