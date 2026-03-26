"""
backend/data/fetch_weather.py

Fetches game-time weather for MLB stadiums via Open-Meteo (free, no API key).

Park info covers all 30 current stadiums plus renamed/replaced venues back to 2015.
For dome/closed-roof parks, weather features are returned as None (no weather effect).

Outfield direction = bearing FROM home plate TOWARD center field (degrees clockwise
from North). Used to compute wind_out_mph: the wind component blowing toward the
outfield (positive = blowing out = more home runs = harder NRFI).

Primary functions:
    get_park_info(park_name)            → dict | None
    get_weather_for_game(park, date, hour_local=19) → dict
    fetch_weather_for_park_daterange(park, start, end) → pd.DataFrame
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_REQUEST_TIMEOUT = 20

# ---------------------------------------------------------------------------
# Park metadata
# ---------------------------------------------------------------------------
# outfield_dir: compass bearing (0=N, 90=E, 180=S, 270=W) from HP to CF.
# is_dome: True for fixed domes and retractable roofs that are typically closed.
#          Open-air and typically-open retractable roofs → False.
# tz: IANA timezone string for the park's city.
#
# NOTE: outfield directions are approximate (±15°). Precision matters less than
# getting the hemisphere right (in vs out).

PARK_INFO: dict[str, dict[str, Any]] = {
    # ---- American League East ----
    "Fenway Park":                     {"lat": 42.3467, "lon": -71.0972, "outfield_dir":  40, "is_dome": False, "tz": "America/New_York"},
    "Yankee Stadium":                  {"lat": 40.8296, "lon": -73.9262, "outfield_dir":  35, "is_dome": False, "tz": "America/New_York"},
    "Rogers Centre":                   {"lat": 43.6414, "lon": -79.3894, "outfield_dir":  40, "is_dome": True,  "tz": "America/Toronto"},
    "Tropicana Field":                 {"lat": 27.7683, "lon": -82.6534, "outfield_dir": 355, "is_dome": True,  "tz": "America/New_York"},
    "Camden Yards":                    {"lat": 39.2838, "lon": -76.6218, "outfield_dir":  60, "is_dome": False, "tz": "America/New_York"},
    "Oriole Park at Camden Yards":     {"lat": 39.2838, "lon": -76.6218, "outfield_dir":  60, "is_dome": False, "tz": "America/New_York"},
    # ---- American League Central ----
    "Guaranteed Rate Field":           {"lat": 41.8300, "lon": -87.6339, "outfield_dir": 170, "is_dome": False, "tz": "America/Chicago"},
    "U.S. Cellular Field":             {"lat": 41.8300, "lon": -87.6339, "outfield_dir": 170, "is_dome": False, "tz": "America/Chicago"},
    "Progressive Field":               {"lat": 41.4954, "lon": -81.6852, "outfield_dir": 220, "is_dome": False, "tz": "America/New_York"},
    "Comerica Park":                   {"lat": 42.3390, "lon": -83.0485, "outfield_dir": 125, "is_dome": False, "tz": "America/Detroit"},
    "Kauffman Stadium":                {"lat": 39.0514, "lon": -94.4803, "outfield_dir":  50, "is_dome": False, "tz": "America/Chicago"},
    "Target Field":                    {"lat": 44.9817, "lon": -93.2781, "outfield_dir":  40, "is_dome": False, "tz": "America/Chicago"},
    # ---- American League West ----
    "Angel Stadium":                   {"lat": 33.8003, "lon": -117.8827, "outfield_dir": 65, "is_dome": False, "tz": "America/Los_Angeles"},
    "Oakland Coliseum":                {"lat": 37.7516, "lon": -122.2005, "outfield_dir": 175, "is_dome": False, "tz": "America/Los_Angeles"},
    "RingCentral Coliseum":            {"lat": 37.7516, "lon": -122.2005, "outfield_dir": 175, "is_dome": False, "tz": "America/Los_Angeles"},
    "Oakland-Alameda County Coliseum": {"lat": 37.7516, "lon": -122.2005, "outfield_dir": 175, "is_dome": False, "tz": "America/Los_Angeles"},
    "T-Mobile Park":                   {"lat": 47.5914, "lon": -122.3326, "outfield_dir":  50, "is_dome": False, "tz": "America/Los_Angeles"},
    "Safeco Field":                    {"lat": 47.5914, "lon": -122.3326, "outfield_dir":  50, "is_dome": False, "tz": "America/Los_Angeles"},
    "Globe Life Field":                {"lat": 32.7473, "lon": -97.0842,  "outfield_dir":  30, "is_dome": True,  "tz": "America/Chicago"},
    "Globe Life Park in Arlington":    {"lat": 32.7510, "lon": -97.0823,  "outfield_dir":  30, "is_dome": False, "tz": "America/Chicago"},
    "Minute Maid Park":                {"lat": 29.7572, "lon": -95.3551,  "outfield_dir":  30, "is_dome": False, "tz": "America/Chicago"},
    # ---- National League East ----
    "Truist Park":                     {"lat": 33.8908, "lon": -84.4681, "outfield_dir":  45, "is_dome": False, "tz": "America/New_York"},
    "SunTrust Park":                   {"lat": 33.8908, "lon": -84.4681, "outfield_dir":  45, "is_dome": False, "tz": "America/New_York"},
    "Turner Field":                    {"lat": 33.7354, "lon": -84.3896, "outfield_dir":  70, "is_dome": False, "tz": "America/New_York"},
    "Nationals Park":                  {"lat": 38.8730, "lon": -77.0074, "outfield_dir":  30, "is_dome": False, "tz": "America/New_York"},
    "Citizens Bank Park":              {"lat": 39.9061, "lon": -75.1665, "outfield_dir": 355, "is_dome": False, "tz": "America/New_York"},
    "Citi Field":                      {"lat": 40.7571, "lon": -73.8458, "outfield_dir":  50, "is_dome": False, "tz": "America/New_York"},
    "loanDepot park":                  {"lat": 25.7781, "lon": -80.2196, "outfield_dir":  10, "is_dome": False, "tz": "America/New_York"},
    "Marlins Park":                    {"lat": 25.7781, "lon": -80.2196, "outfield_dir":  10, "is_dome": False, "tz": "America/New_York"},
    # ---- National League Central ----
    "Wrigley Field":                   {"lat": 41.9484, "lon": -87.6553, "outfield_dir":  10, "is_dome": False, "tz": "America/Chicago"},
    "Busch Stadium":                   {"lat": 38.6226, "lon": -90.1928, "outfield_dir": 330, "is_dome": False, "tz": "America/Chicago"},
    "Great American Ball Park":        {"lat": 39.0979, "lon": -84.5078, "outfield_dir": 340, "is_dome": False, "tz": "America/New_York"},
    "PNC Park":                        {"lat": 40.4469, "lon": -80.0058, "outfield_dir":  10, "is_dome": False, "tz": "America/New_York"},
    "American Family Field":           {"lat": 43.0280, "lon": -87.9712, "outfield_dir":  35, "is_dome": False, "tz": "America/Chicago"},
    "Miller Park":                     {"lat": 43.0280, "lon": -87.9712, "outfield_dir":  35, "is_dome": False, "tz": "America/Chicago"},
    # ---- National League West ----
    "Dodger Stadium":                  {"lat": 34.0739, "lon": -118.2400, "outfield_dir": 320, "is_dome": False, "tz": "America/Los_Angeles"},
    "Oracle Park":                     {"lat": 37.7786, "lon": -122.3893, "outfield_dir":  55, "is_dome": False, "tz": "America/Los_Angeles"},
    "Petco Park":                      {"lat": 32.7076, "lon": -117.1571, "outfield_dir": 325, "is_dome": False, "tz": "America/Los_Angeles"},
    "Chase Field":                     {"lat": 33.4455, "lon": -112.0667, "outfield_dir": 320, "is_dome": False, "tz": "America/Phoenix"},
    "Coors Field":                     {"lat": 39.7559, "lon": -104.9942, "outfield_dir":  55, "is_dome": False, "tz": "America/Denver"},
    # ---- Historical aliases (renamed parks) ----
    "AT&T Park":                       {"lat": 37.7786, "lon": -122.3893, "outfield_dir":  55, "is_dome": False, "tz": "America/Los_Angeles"},  # SF pre-2019
    "SBC Park":                        {"lat": 37.7786, "lon": -122.3893, "outfield_dir":  55, "is_dome": False, "tz": "America/Los_Angeles"},  # SF pre-2004
    "O.co Coliseum":                   {"lat": 37.7516, "lon": -122.2005, "outfield_dir": 175, "is_dome": False, "tz": "America/Los_Angeles"},  # OAK
    "Oakland Coliseum":                {"lat": 37.7516, "lon": -122.2005, "outfield_dir": 175, "is_dome": False, "tz": "America/Los_Angeles"},  # OAK
    "Oriole Park at Camden Yards":     {"lat": 39.2838, "lon": -76.6218,  "outfield_dir":  60, "is_dome": False, "tz": "America/New_York"},
    "Angel Stadium of Anaheim":        {"lat": 33.8003, "lon": -117.8827, "outfield_dir":  65, "is_dome": False, "tz": "America/Los_Angeles"},
    # ---- Other/neutral site ----
    "Estadio Alfredo Harp Helú":       {"lat": 19.4824, "lon": -99.0970, "outfield_dir":  45, "is_dome": False, "tz": "America/Mexico_City"},
    "London Stadium":                  {"lat": 51.5386, "lon":  -0.0161, "outfield_dir":   0, "is_dome": False, "tz": "Europe/London"},
}


def get_park_info(park_name: str | None) -> dict[str, Any] | None:
    """Return park metadata dict or None if the park is unknown."""
    if not park_name:
        return None
    return PARK_INFO.get(park_name)


# ---------------------------------------------------------------------------
# Wind component calculation
# ---------------------------------------------------------------------------

def _wind_out_component(wind_speed: float, wind_dir_from: float, outfield_dir: float) -> float:
    """
    Compute the wind component blowing toward the outfield (HP → CF direction).

    Args:
        wind_speed: wind speed (any unit, output is in same unit)
        wind_dir_from: meteorological direction wind is COMING FROM (0=N, 90=E)
        outfield_dir: compass bearing from HP toward CF (0=N, 90=E)

    Returns:
        Positive = blowing OUT (toward CF) — inflates scoring.
        Negative = blowing IN (from CF) — suppresses scoring.
    """
    wind_toward = (wind_dir_from + 180.0) % 360.0
    angle_diff = math.radians(wind_toward - outfield_dir)
    return round(wind_speed * math.cos(angle_diff), 2)


# ---------------------------------------------------------------------------
# Open-Meteo API
# ---------------------------------------------------------------------------

def _open_meteo_request(lat: float, lon: float, start: str, end: str, tz: str) -> dict | None:
    """
    Fetch hourly temperature + wind data from Open-Meteo for a date range.
    Uses the archive API for past dates, forecast API for today/future.

    Returns raw JSON response dict or None on failure.
    """
    today_str = str(date.today())
    use_forecast = start >= today_str

    url = _FORECAST_URL if use_forecast else _ARCHIVE_URL
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": tz,
    }
    # forecast API accepts start_date/end_date directly — don't also pass forecast_days

    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning("Open-Meteo rate limited — waiting %ds (attempt %d/4)...", wait, attempt + 1)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == 3:
                logger.warning("Open-Meteo request failed after 4 attempts (%s → %s): %s", start, end, exc)
                return None
            time.sleep(5 * (attempt + 1))
    return None


def _parse_hourly(data: dict) -> dict[str, dict[int, tuple[float, float, float]]]:
    """
    Parse Open-Meteo hourly response into a lookup dict.

    Returns: {date_str: {hour_int: (temperature_f, wind_speed_mph, wind_dir_deg)}}
    """
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    speeds = hourly.get("wind_speed_10m", [])
    dirs = hourly.get("wind_direction_10m", [])

    result: dict[str, dict[int, tuple[float, float, float]]] = {}
    for i, t in enumerate(times):
        # t is like "2023-04-15T19:00"
        try:
            dt_str, hr_str = t.split("T")
            hour = int(hr_str[:2])
            result.setdefault(dt_str, {})[hour] = (
                temps[i] if i < len(temps) else None,
                speeds[i] if i < len(speeds) else None,
                dirs[i] if i < len(dirs) else None,
            )
        except (ValueError, IndexError):
            continue
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_weather_for_game(
    park: str | None,
    game_date: str,
    game_hour_local: int = 19,
) -> dict[str, Any]:
    """
    Return weather features for a single game.

    Args:
        park: venue name matching PARK_INFO keys
        game_date: YYYY-MM-DD string
        game_hour_local: local hour of game start (default 19 = 7 PM)

    Returns dict with:
        temperature_f   : float | None
        wind_speed_mph  : float | None
        wind_out_mph    : float | None  (positive = blowing out toward CF)
        is_dome         : float  (1.0 or 0.0)
    """
    null_result: dict[str, Any] = {
        "temperature_f": None,
        "wind_speed_mph": None,
        "wind_out_mph": None,
        "is_dome": 0.0,
    }

    info = get_park_info(park)
    if info is None:
        logger.debug("Unknown park '%s' — weather features will be None.", park)
        return null_result

    if info["is_dome"]:
        return {"temperature_f": None, "wind_speed_mph": None, "wind_out_mph": None, "is_dome": 1.0}

    data = _open_meteo_request(info["lat"], info["lon"], game_date, game_date, info["tz"])
    if data is None:
        return null_result

    hourly = _parse_hourly(data)
    date_hours = hourly.get(game_date, {})

    # Try requested hour, then ±1 hour fallback
    row = (
        date_hours.get(game_hour_local)
        or date_hours.get(game_hour_local - 1)
        or date_hours.get(game_hour_local + 1)
    )
    if row is None:
        return null_result

    temp_f, wind_spd, wind_dir = row
    wind_out = (
        _wind_out_component(wind_spd, wind_dir, info["outfield_dir"])
        if wind_spd is not None and wind_dir is not None
        else None
    )

    return {
        "temperature_f": round(temp_f, 1) if temp_f is not None else None,
        "wind_speed_mph": round(wind_spd, 1) if wind_spd is not None else None,
        "wind_out_mph": wind_out,
        "is_dome": 0.0,
    }


def fetch_weather_for_park_daterange(
    park: str,
    start_date: str,
    end_date: str,
) -> dict[str, dict[int, tuple[float | None, float | None, float | None]]]:
    """
    Bulk fetch hourly weather for a park over a date range.
    Used by the backfill script to avoid per-game API calls.

    Returns: {date_str: {hour: (temperature_f, wind_speed_mph, wind_dir_deg)}}
    Returns empty dict for dome parks or on API failure.
    """
    info = get_park_info(park)
    if info is None or info["is_dome"]:
        return {}

    data = _open_meteo_request(info["lat"], info["lon"], start_date, end_date, info["tz"])
    if data is None:
        return {}

    return _parse_hourly(data)
