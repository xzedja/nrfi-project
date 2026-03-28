"""
scripts/check_historical_coverage.py

Checks NRFI odds coverage across multiple dates in 2024 and 2025
to determine if historical data is reliable enough to use for training.

Usage:
    python scripts/check_historical_coverage.py
"""

import sys
import time
import requests

sys.path.insert(0, ".")

from backend.core.config import get_settings

settings = get_settings()

DATES = [
    "2025-04-10",
    "2025-05-01",
    "2025-06-01",
    "2025-07-20",
    "2025-08-15",
    "2025-09-01",
    "2024-04-15",
    "2024-07-01",
    "2024-09-01",
]

print(f"{'Date':<12}  {'Matchup':<35}  {'NRFI Available':<16}  Remaining")
print("-" * 85)

for d in DATES:
    r = requests.get(
        "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events",
        params={
            "apiKey": settings.odds_api_key,
            "date": f"{d}T18:00:00Z",
            "dateFormat": "iso",
        },
        timeout=10,
    )
    events = r.json().get("data", [])
    if not events:
        print(f"{d:<12}  {'(no events)':<35}  {'—':<16}")
        time.sleep(1)
        continue

    event = events[0]
    event_id = event["id"]
    matchup = f"{event['away_team'][:15]} @ {event['home_team'][:15]}"

    time.sleep(1)

    r2 = requests.get(
        f"https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events/{event_id}/odds",
        params={
            "apiKey": settings.odds_api_key,
            "date": f"{d}T18:00:00Z",
            "regions": "us",
            "markets": "totals_1st_1_innings",
            "oddsFormat": "american",
        },
        timeout=10,
    )
    remaining = r2.headers.get("x-requests-remaining", "?")
    bms = r2.json().get("data", {}).get("bookmakers", [])
    has_nrfi = any(
        m["key"] == "totals_1st_1_innings"
        for bm in bms
        for m in bm.get("markets", [])
    )
    book_count = sum(
        1 for bm in bms
        if any(m["key"] == "totals_1st_1_innings" for m in bm.get("markets", []))
    )
    result = f"YES ({book_count} books)" if has_nrfi else "NO"
    print(f"{d:<12}  {matchup:<35}  {result:<16}  {remaining}")
    time.sleep(2)

print("\nDone.")
