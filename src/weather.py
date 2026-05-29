"""
weather.py – Fetch game-time weather using Open-Meteo (no API key needed).

Steps:
1. Geocode the stadium city via Open-Meteo Geocoding API.
2. Pull hourly forecast for temperature, wind speed, precipitation.
3. Return a WeatherInfo dict.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from config import WEATHER_API_BASE, GEOCODE_API_BASE
from src.cache import cache_get, cache_set
from src.utils import safe_get, to_float

logger = logging.getLogger(__name__)

# Stadium → (lat, lon) for direct lookup (avoids geocoding errors)
STADIUM_COORDS: dict[str, tuple[float, float]] = {
    "Yankee Stadium":              (40.8296, -73.9262),
    "Fenway Park":                 (42.3467, -71.0972),
    "Wrigley Field":               (41.9484, -87.6553),
    "Dodger Stadium":              (34.0739, -118.2400),
    "Oracle Park":                 (37.7786, -122.3893),
    "Coors Field":                 (39.7560, -104.9942),
    "Globe Life Field":            (32.7473, -97.0831),
    "Minute Maid Park":            (29.7572, -95.3555),
    "Great American Ball Park":    (39.0979, -84.5082),
    "Petco Park":                  (32.7076, -117.1570),
    "Citizens Bank Park":          (39.9058, -75.1665),
    "Truist Park":                 (33.8908, -84.4678),
    "Camden Yards":                (39.2838, -76.6216),
    "PNC Park":                    (40.4469, -80.0057),
    "Busch Stadium":               (38.6226, -90.1928),
    "American Family Field":       (43.0280, -87.9712),
    "Chase Field":                 (33.4455, -112.0667),
    "T-Mobile Park":               (47.5915, -122.3325),
    "Target Field":                (44.9817, -93.2784),
    "Kauffman Stadium":            (39.0517, -94.4803),
    "Angel Stadium":               (33.8003, -117.8827),
    "loanDepot park":              (25.7781, -80.2198),
    "Progressive Field":           (41.4962, -81.6852),
    "Citi Field":                  (40.7571, -73.8458),
    "Rogers Centre":               (43.6414, -79.3894),
    "Nationals Park":              (38.8730, -77.0074),
    "Guaranteed Rate Field":       (41.8300, -87.6339),
    "Tropicana Field":             (27.7683, -82.6534),
    "Oakland Coliseum":            (37.7516, -122.2005),
}


def fetch_weather(venue: str, game_time_utc: str) -> dict:
    """Return weather dict for *venue* at *game_time_utc* (ISO 8601 string)."""
    cache_key = f"weather_{venue.replace(' ', '_')}_{game_time_utc[:13]}"
    cached = cache_get(cache_key, "weather")
    if cached is not None:
        return cached

    result = _empty_weather(venue)

    coords = STADIUM_COORDS.get(venue)
    if coords is None:
        coords = _geocode(venue)
    if coords is None:
        logger.warning("Could not geocode venue: %s", venue)
        result["note"] = "Weather unavailable: venue not geocoded"
        return result

    lat, lon = coords

    # Parse game time
    try:
        dt = datetime.fromisoformat(game_time_utc.replace("Z", "+00:00"))
    except Exception:
        result["note"] = "Weather unavailable: could not parse game time"
        return result

    # Open-Meteo hourly forecast
    params = {
        "latitude":           lat,
        "longitude":          lon,
        "hourly":             "temperature_2m,windspeed_10m,winddirection_10m,precipitation_probability,weathercode",
        "wind_speed_unit":    "mph",
        "temperature_unit":   "fahrenheit",
        "forecast_days":      3,
        "timezone":           "UTC",
    }
    data = safe_get(WEATHER_API_BASE, params)
    if data is None:
        result["note"] = "Weather API unavailable"
        return result

    try:
        hourly      = data["hourly"]
        times       = hourly["time"]                     # list of "2025-05-29T14:00"
        target_hour = dt.strftime("%Y-%m-%dT%H:00")
        if target_hour not in times:
            # Find closest hour
            target_ts  = dt.timestamp()
            time_objs  = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in times]
            diffs      = [abs(t.timestamp() - target_ts) for t in time_objs]
            idx        = diffs.index(min(diffs))
        else:
            idx = times.index(target_hour)

        temp        = to_float(hourly["temperature_2m"][idx])
        wind_speed  = to_float(hourly["windspeed_10m"][idx])
        wind_dir    = to_float(hourly["winddirection_10m"][idx])
        precip_prob = to_float(hourly["precipitation_probability"][idx])
        wcode       = to_float(hourly["weathercode"][idx])

        # Interpret weather risk
        risk = _weather_risk(temp, wind_speed, precip_prob, wcode)

        result.update({
            "temperature_f":  temp,
            "wind_speed_mph": wind_speed,
            "wind_direction": _wind_direction_label(wind_dir),
            "precip_prob_pct":precip_prob,
            "weather_code":   wcode,
            "risk":           risk,
            "risk_flag":      risk in ("High", "Very High"),
            "note":           None,
        })
    except Exception as exc:
        logger.warning("Weather parse error for %s: %s", venue, exc)
        result["note"] = f"Weather parse error: {exc}"

    cache_set(cache_key, result)
    return result


def _empty_weather(venue: str) -> dict:
    return {
        "venue":          venue,
        "temperature_f":  None,
        "wind_speed_mph": None,
        "wind_direction": None,
        "precip_prob_pct":None,
        "weather_code":   None,
        "risk":           "Unknown",
        "risk_flag":      False,
        "note":           "Weather data not loaded",
    }


def _geocode(venue: str) -> Optional[tuple[float, float]]:
    """Use Open-Meteo Geocoding API to find lat/lon for a venue."""
    data = safe_get(GEOCODE_API_BASE, {"name": venue, "count": 1, "language": "en"})
    if not data:
        return None
    results = data.get("results", [])
    if not results:
        return None
    r = results[0]
    return to_float(r.get("latitude")), to_float(r.get("longitude"))


def _weather_risk(temp: Optional[float], wind: Optional[float],
                   precip: Optional[float], code: Optional[float]) -> str:
    if temp is None or wind is None:
        return "Unknown"
    risk = 0
    if precip is not None and precip > 40:
        risk += 2
    if wind is not None and wind > 20:
        risk += 2
    if wind is not None and wind > 15:
        risk += 1
    if temp is not None and temp < 40:
        risk += 1
    if code is not None and code >= 61:   # rain codes
        risk += 2

    if risk >= 4:
        return "Very High"
    if risk >= 3:
        return "High"
    if risk >= 2:
        return "Moderate"
    if risk >= 1:
        return "Low"
    return "Minimal"


def _wind_direction_label(degrees: Optional[float]) -> Optional[str]:
    if degrees is None:
        return None
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(degrees / 22.5) % 16
    return dirs[idx]
