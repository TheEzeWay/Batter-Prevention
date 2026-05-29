"""
mlb_schedule.py – Fetch today's MLB schedule from the MLB Stats API.

Returns a list of GameInfo dicts:
    game_pk, game_time, away_team, home_team, venue,
    away_pitcher, home_pitcher, away_pitcher_hand, home_pitcher_hand,
    away_pitcher_id, home_pitcher_id, away_team_id, home_team_id,
    status
"""

import logging
from datetime import date
from typing import Optional

from config import MLB_API_BASE
from src.cache import cache_get, cache_set
from src.utils import safe_get

logger = logging.getLogger(__name__)


def fetch_schedule(game_date: date) -> list[dict]:
    """Return list of game dicts for *game_date*. Uses cache when fresh."""
    date_str = game_date.strftime("%Y-%m-%d")
    cache_key = f"schedule_{date_str}"
    cached = cache_get(cache_key, "schedule")
    if cached is not None:
        logger.info("Schedule loaded from cache for %s", date_str)
        return cached

    url = f"{MLB_API_BASE}/schedule"
    params = {
        "sportId":    1,
        "date":       date_str,
        "hydrate":    "probablePitcher(note),team,venue,linescore,weather",
        "fields":     (
            "dates,games,gamePk,gameDate,status,teams,team,name,abbreviation,"
            "venue,probablePitcher,id,fullName,pitchHand,code,statusCode,"
            "abstractGameState"
        ),
    }
    data = safe_get(url, params)
    if data is None:
        logger.warning("Could not fetch schedule for %s", date_str)
        return []

    games: list[dict] = []
    for date_block in data.get("dates", []):
        for g in date_block.get("games", []):
            try:
                info = _parse_game(g)
                if info:
                    games.append(info)
            except Exception as exc:
                logger.warning("Error parsing game %s: %s", g.get("gamePk"), exc)

    cache_set(cache_key, games)
    logger.info("Fetched %d games for %s", len(games), date_str)
    return games


def _parse_game(g: dict) -> Optional[dict]:
    teams   = g.get("teams", {})
    away_t  = teams.get("away", {})
    home_t  = teams.get("home", {})
    venue   = g.get("venue", {}).get("name", "Unknown Venue")
    status  = g.get("status", {})

    away_team    = away_t.get("team", {}).get("name", "Unknown")
    home_team    = home_t.get("team", {}).get("name", "Unknown")
    away_abbrev  = away_t.get("team", {}).get("abbreviation", "???")
    home_abbrev  = home_t.get("team", {}).get("abbreviation", "???")
    away_team_id = away_t.get("team", {}).get("id")
    home_team_id = home_t.get("team", {}).get("id")

    # Probable pitchers
    away_pp  = away_t.get("probablePitcher", {})
    home_pp  = home_t.get("probablePitcher", {})

    away_pitcher      = away_pp.get("fullName")
    home_pitcher      = home_pp.get("fullName")
    away_pitcher_id   = away_pp.get("id")
    home_pitcher_id   = home_pp.get("id")
    away_pitcher_hand = away_pp.get("pitchHand", {}).get("code")
    home_pitcher_hand = home_pp.get("pitchHand", {}).get("code")

    # Game time (UTC string → keep raw, format in UI)
    game_time_raw = g.get("gameDate", "")

    return {
        "game_pk":           g.get("gamePk"),
        "game_time_utc":     game_time_raw,
        "away_team":         away_team,
        "home_team":         home_team,
        "away_abbrev":       away_abbrev,
        "home_abbrev":       home_abbrev,
        "away_team_id":      away_team_id,
        "home_team_id":      home_team_id,
        "venue":             venue,
        "away_pitcher":      away_pitcher,
        "home_pitcher":      home_pitcher,
        "away_pitcher_id":   away_pitcher_id,
        "home_pitcher_id":   home_pitcher_id,
        "away_pitcher_hand": away_pitcher_hand,
        "home_pitcher_hand": home_pitcher_hand,
        "status_code":       status.get("statusCode", ""),
        "abstract_state":    status.get("abstractGameState", "Preview"),
    }
