"""
player_ids.py – Resolve player names to MLB Stats API IDs and MLBAM IDs.

The MLB Stats API uses the same integer IDs as Baseball Savant (MLBAM IDs),
so one lookup covers both.
"""

import logging
from typing import Optional

from config import MLB_API_BASE
from src.cache import cache_get, cache_set
from src.utils import safe_get

logger = logging.getLogger(__name__)


def get_player_id(name: str) -> Optional[int]:
    """Search the MLB Stats API people endpoint by name. Returns MLBAM ID."""
    cache_key = f"player_id_{name.lower().replace(' ', '_')}"
    cached = cache_get(cache_key, "player_ids")
    if cached is not None:
        return cached

    url   = f"{MLB_API_BASE}/people/search"
    data  = safe_get(url, {"names": name, "sportId": 1})
    if data is None:
        return None

    people = data.get("people", [])
    if not people:
        logger.warning("No player found for name: %s", name)
        return None

    # Prefer active players
    for p in people:
        if p.get("active"):
            pid = p.get("id")
            cache_set(cache_key, pid)
            return pid

    pid = people[0].get("id")
    cache_set(cache_key, pid)
    return pid


def get_player_info(player_id: int) -> dict:
    """Fetch basic player info (name, position, bats, throws) by MLBAM ID."""
    cache_key = f"player_info_{player_id}"
    cached = cache_get(cache_key, "player_ids")
    if cached is not None:
        return cached

    url  = f"{MLB_API_BASE}/people/{player_id}"
    data = safe_get(url, {"hydrate": "currentTeam"})
    if data is None:
        return {}

    people = data.get("people", [{}])
    if not people:
        return {}
    p    = people[0]
    info = {
        "id":           p.get("id"),
        "full_name":    p.get("fullName"),
        "bats":         p.get("batSide",   {}).get("code"),
        "throws":       p.get("pitchHand", {}).get("code"),
        "position":     p.get("primaryPosition", {}).get("abbreviation"),
        "active":       p.get("active", False),
        "current_team": p.get("currentTeam", {}).get("name"),
        "team_id":      p.get("currentTeam", {}).get("id"),
    }
    cache_set(cache_key, info)
    return info


def resolve_roster_ids(team_id: int, roster_type: str = "active") -> dict[str, int]:
    """Return {player_name: mlbam_id} for all players on a team's roster."""
    cache_key = f"roster_{team_id}_{roster_type}"
    cached = cache_get(cache_key, "player_ids")
    if cached is not None:
        return cached

    url  = f"{MLB_API_BASE}/teams/{team_id}/roster/{roster_type}"
    data = safe_get(url)
    if data is None:
        return {}

    result = {}
    for entry in data.get("roster", []):
        person = entry.get("person", {})
        name   = person.get("fullName", "")
        pid    = person.get("id")
        if name and pid:
            result[name] = pid

    cache_set(cache_key, result)
    return result
