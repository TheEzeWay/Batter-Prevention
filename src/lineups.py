"""
lineups.py – Fetch confirmed and projected lineups.

Priority:
1. MLB Stats API live boxscore (confirmed when game is live / lineup posted)
2. MLB Stats API /game/{pk}/liveGameV1 lineupCard
3. RosterResource projected lineups (HTML parse, no API key needed)

Returns for each team:
    {
      "team_id": int,
      "team_name": str,
      "status": "confirmed" | "projected" | "unavailable",
      "players": [
          {"lineup_spot": 1, "player_id": int, "player_name": str,
           "bats": "R"/"L"/"S", "position": str}
      ]
    }
"""

import logging
import re
from datetime import date
from typing import Optional

from config import MLB_API_BASE, MLB_API_BASE_V11
from src.cache import cache_get, cache_set
from src.utils import safe_get, safe_get_text

logger = logging.getLogger(__name__)


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_lineups_for_game(game_pk: int, away_team_id: int, home_team_id: int,
                            away_name: str, home_name: str,
                            game_date: date) -> dict[str, dict]:
    """Return {'away': lineup_dict, 'home': lineup_dict}."""
    cache_key = f"lineup_{game_pk}"
    cached = cache_get(cache_key, "lineups")
    if cached is not None:
        return cached

    result = {
        "away": _empty_lineup(away_team_id, away_name),
        "home": _empty_lineup(home_team_id, home_name),
    }

    # Try live boxscore first (works pre-game once lineup is posted)
    confirmed = _try_boxscore(game_pk, away_team_id, home_team_id, away_name, home_name)
    if confirmed:
        result.update(confirmed)
        cache_set(cache_key, result)
        return result

    # Fall back to RosterResource projected
    projected = _try_rosterresource(away_name, home_name, game_date)
    if projected:
        result.update(projected)

    cache_set(cache_key, result)
    return result


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _empty_lineup(team_id: int, team_name: str) -> dict:
    return {
        "team_id":   team_id,
        "team_name": team_name,
        "status":    "unavailable",
        "players":   [],
    }


def _try_boxscore(game_pk: int, away_id: int, home_id: int,
                   away_name: str, home_name: str) -> Optional[dict]:
    """Pull lineup from MLB Stats API boxscore endpoint."""
    url  = f"{MLB_API_BASE}/game/{game_pk}/boxscore"
    data = safe_get(url)
    if data is None:
        return None

    teams_data = data.get("teams", {})
    result     = {}

    for side, side_key, tid, tname in [
        ("away", "away", away_id, away_name),
        ("home", "home", home_id, home_name),
    ]:
        side_data = teams_data.get(side_key, {})
        batters   = side_data.get("battingOrder", [])
        players   = side_data.get("players", {})

        if not batters:
            continue

        lineup_players = []
        for spot, pid_raw in enumerate(batters, start=1):
            pid  = int(str(pid_raw).lstrip("ID"))
            pkey = f"ID{pid}"
            info = players.get(pkey, {}).get("person", {})
            ab   = players.get(pkey, {}).get("allPositions", [{}])
            pos  = ab[0].get("abbreviation", "?") if ab else "?"
            bats_code = players.get(pkey, {}).get("batSide", {}).get("code", "?")

            lineup_players.append({
                "lineup_spot":   spot,
                "player_id":     pid,
                "player_name":   info.get("fullName", f"Player {pid}"),
                "bats":          bats_code,
                "position":      pos,
            })

        if lineup_players:
            result[side] = {
                "team_id":   tid,
                "team_name": tname,
                "status":    "confirmed",
                "players":   lineup_players,
            }

    return result if result else None


def _try_rosterresource(away_name: str, home_name: str, game_date: date) -> Optional[dict]:
    """
    Scrape RosterResource for projected lineups.
    Returns partial dict keyed 'away' / 'home' with status='projected'.
    """
    from src.utils import safe_get_text
    url  = "https://www.rosterresource.com/mlb-starting-lineups"
    html = safe_get_text(url)
    if not html:
        logger.warning("RosterResource unavailable for projected lineups")
        return None

    result = {}
    # RosterResource uses team name blocks; do a best-effort text parse.
    # Since the page structure changes, we extract lineup patterns:
    # e.g.  "1. Jose Altuve (2B)"
    lineup_pattern = re.compile(
        r'(\d)\.\s+([A-Z][a-z]+(?:\s+[A-Z][a-z\-\']+)+)\s+\(([A-Z1-9]{1,3})\)'
    )

    # Try to find blocks near team names
    for side, team_name in [("away", away_name), ("home", home_name)]:
        # Find a window around the team name mention
        idx = html.find(team_name)
        if idx == -1:
            # Try abbreviated search
            abbrev = team_name.split()[-1]  # e.g. "Astros"
            idx = html.find(abbrev)
        if idx == -1:
            continue

        window = html[idx: idx + 3000]
        matches = lineup_pattern.findall(window)
        if len(matches) >= 5:
            players = []
            for m in matches[:9]:
                players.append({
                    "lineup_spot":  int(m[0]),
                    "player_id":    None,  # ID resolved later
                    "player_name":  m[1].strip(),
                    "bats":         "?",
                    "position":     m[2],
                })
            result[side] = {
                "team_id":   None,
                "team_name": team_name,
                "status":    "projected",
                "players":   players,
            }

    return result if result else None
