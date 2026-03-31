"""
scripts/test_odds_api.py

Probes The Odds API to find which historical endpoint combination
returns event IDs for past MLB games.

Usage:
    python scripts/test_odds_api.py
    python scripts/test_odds_api.py --date 2024-07-15
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

sys.path.insert(0, ".")

from backend.core.config import get_settings

_BASE = "https://api.the-odds-api.com/v4"
_TIMEOUT = 15


def probe(label: str, url: str, params: dict) -> list | dict | None:
    settings = get_settings()
    params["apiKey"] = settings.odds_api_key
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"URL : {url}")
    print(f"PARAMS (excl. key): { {k:v for k,v in params.items() if k != 'apiKey'} }")
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        print(f"STATUS: {resp.status_code}")
        print(f"CREDITS used: {resp.headers.get('x-requests-used','?')}  remaining: {resp.headers.get('x-requests-remaining','?')}")
        data = resp.json()
        if isinstance(data, list):
            print(f"RESULT: list with {len(data)} items")
            if data:
                print(f"FIRST ITEM KEYS: {list(data[0].keys())}")
                print(f"FIRST ITEM (truncated):")
                item = data[0]
                # Show just top-level fields, truncate bookmakers
                summary = {k: v for k, v in item.items() if k != "bookmakers"}
                print(json.dumps(summary, indent=2, default=str))
        elif isinstance(data, dict):
            print(f"RESULT: dict with keys {list(data.keys())}")
            inner = data.get("data", data)
            if isinstance(inner, list):
                print(f"  data[] has {len(inner)} items")
                if inner:
                    print(f"  FIRST ITEM KEYS: {list(inner[0].keys())}")
                    summary = {k: v for k, v in inner[0].items() if k != "bookmakers"}
                    print(json.dumps(summary, indent=2, default=str))
            else:
                print(json.dumps(data, indent=2, default=str)[:500])
        return data
    except Exception as exc:
        print(f"ERROR: {exc}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2024-07-15",
                        help="Historical game date to test (YYYY-MM-DD)")
    args = parser.parse_args()
    d = args.date
    snapshot = f"{d}T17:00:00Z"

    # 1. Standard events endpoint with date snapshot param
    probe(
        "Events endpoint with date= snapshot",
        f"{_BASE}/sports/baseball_mlb/events",
        {"date": snapshot},
    )

    # 2. Events endpoint with commenceTimeFrom/To
    from datetime import datetime, timedelta
    next_d = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    probe(
        "Events endpoint with commenceTimeFrom/To",
        f"{_BASE}/sports/baseball_mlb/events",
        {
            "commenceTimeFrom": f"{d}T00:00:00Z",
            "commenceTimeTo":   f"{next_d}T12:00:00Z",
        },
    )

    # 3. Odds-history with totals (should work — standard market)
    data = probe(
        "odds-history with markets=totals",
        f"{_BASE}/sports/baseball_mlb/odds-history",
        {
            "regions":    "us",
            "markets":    "totals",
            "oddsFormat": "american",
            "date":       snapshot,
        },
    )

    # 4. Odds-history with totals_1st_1_innings (period market — known 422)
    probe(
        "odds-history with markets=totals_1st_1_innings",
        f"{_BASE}/sports/baseball_mlb/odds-history",
        {
            "regions":    "us",
            "markets":    "totals_1st_1_innings",
            "oddsFormat": "american",
            "date":       snapshot,
        },
    )

    # 5. If totals returned event data, try fetching period market odds for one event
    event_id = None
    if isinstance(data, dict):
        items = data.get("data", [])
        if items:
            event_id = items[0].get("id")
    elif isinstance(data, list) and data:
        event_id = data[0].get("id")

    if event_id:
        print(f"\n>>> Found event_id from totals response: {event_id}")
        probe(
            f"Event-specific odds (totals_1st_1_innings) with date= snapshot — event {event_id[:8]}...",
            f"{_BASE}/sports/baseball_mlb/events/{event_id}/odds",
            {
                "regions":    "us",
                "markets":    "totals_1st_1_innings",
                "oddsFormat": "american",
                "date":       snapshot,
            },
        )
    else:
        print("\n>>> No event_id found from totals response — skipping event-specific test")
        print("    Try running with a date that has MLB games (April–October)")


if __name__ == "__main__":
    main()
