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

    # 1. CORRECT historical events endpoint (with /historical/ prefix + date param)
    events_data = probe(
        "HISTORICAL events endpoint (/historical/sports/.../events?date=)",
        f"{_BASE}/historical/sports/baseball_mlb/events",
        {"date": snapshot},
    )

    # 2. CORRECT historical featured odds (/historical/sports/.../odds with totals)
    odds_data = probe(
        "HISTORICAL odds endpoint (/historical/sports/.../odds?markets=totals)",
        f"{_BASE}/historical/sports/baseball_mlb/odds",
        {
            "regions":    "us",
            "markets":    "totals",
            "oddsFormat": "american",
            "date":       snapshot,
        },
    )

    # 3. CORRECT historical featured odds with totals_1st_1_innings
    probe(
        "HISTORICAL odds endpoint with totals_1st_1_innings",
        f"{_BASE}/historical/sports/baseball_mlb/odds",
        {
            "regions":    "us",
            "markets":    "totals_1st_1_innings",
            "oddsFormat": "american",
            "date":       snapshot,
        },
    )

    # 4. Extract an event_id from whichever response has data, then test
    #    the historical event-specific endpoint for NRFI period market
    event_id = None
    for resp_data in [events_data, odds_data]:
        if isinstance(resp_data, dict):
            items = resp_data.get("data", [])
            if items:
                event_id = items[0].get("id")
                break
        elif isinstance(resp_data, list) and resp_data:
            event_id = resp_data[0].get("id")
            break

    if event_id:
        print(f"\n>>> Found event_id: {event_id}")
        probe(
            f"HISTORICAL event-specific odds (/historical/.../events/{{id}}/odds) — event {event_id[:8]}...",
            f"{_BASE}/historical/sports/baseball_mlb/events/{event_id}/odds",
            {
                "regions":    "us",
                "markets":    "totals_1st_1_innings",
                "oddsFormat": "american",
                "date":       snapshot,
            },
        )
    else:
        print("\n>>> No event_id found — skipping event-specific test")
        print("    Try a date with regular season MLB games (April–October)")


if __name__ == "__main__":
    main()
