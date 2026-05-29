"""
batter_model.py – Build BatterProfile dataclasses from raw stat dicts.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.statcast_data import (
    get_batter_statcast,
    get_batter_vs_pitch_type,
    get_batter_recent_form,
)

logger = logging.getLogger(__name__)


@dataclass
class BatterProfile:
    # Identity
    player_id:     Optional[int]
    name:          str
    team:          str
    lineup_spot:   int
    bats:          Optional[str]    = None  # "R" / "L" / "S"
    position:      Optional[str]    = None

    # Traditional
    obp:           Optional[float]  = None
    avg:           Optional[float]  = None
    ops:           Optional[float]  = None
    iso:           Optional[float]  = None
    woba:          Optional[float]  = None

    # Expected stats
    xobp:          Optional[float]  = None
    xba:           Optional[float]  = None
    xwoba:         Optional[float]  = None

    # Plate discipline
    k_pct:         Optional[float]  = None
    bb_pct:        Optional[float]  = None
    chase_pct:     Optional[float]  = None
    whiff_pct:     Optional[float]  = None
    contact_pct:   Optional[float]  = None

    # Contact quality
    hard_pct:      Optional[float]  = None
    barrel_pct:    Optional[float]  = None

    # Recent form (rolling OBP)
    obp_7d:        Optional[float]  = None
    obp_15d:       Optional[float]  = None
    obp_30d:       Optional[float]  = None

    # Pitch-type splits: {pitch_type: {whiff_pct, xwoba, k_pct, chase_pct}}
    vs_pitch_types: dict            = field(default_factory=dict)

    # Data quality
    missing_fields: list[str]       = field(default_factory=list)


def build_batter_profile(player_id: Optional[int], name: str, team: str,
                          lineup_spot: int, bats: Optional[str],
                          position: Optional[str], season: int) -> BatterProfile:
    """Construct a BatterProfile from Statcast data."""
    profile = BatterProfile(
        player_id=player_id, name=name, team=team,
        lineup_spot=lineup_spot, bats=bats, position=position,
    )

    if player_id is None:
        profile.missing_fields.append("player_id_unresolved")
        logger.warning("No player_id for %s – stats unavailable", name)
        return profile

    stats = get_batter_statcast(player_id, season)
    if not stats:
        profile.missing_fields.append("all_batter_stats")
        logger.warning("No Statcast data for batter %s (%d)", name, player_id)
        return profile

    profile.obp         = stats.get("obp")
    profile.avg         = stats.get("avg")
    profile.ops         = stats.get("ops")
    profile.iso         = stats.get("iso")
    profile.woba        = stats.get("woba")
    profile.xobp        = stats.get("xobp")
    profile.xba         = stats.get("xba")
    profile.xwoba       = stats.get("xwoba")
    profile.k_pct       = stats.get("k_pct")
    profile.bb_pct      = stats.get("bb_pct")
    profile.chase_pct   = stats.get("chase_pct")
    profile.whiff_pct   = stats.get("whiff_pct")
    profile.contact_pct = stats.get("contact_pct")
    profile.hard_pct    = stats.get("hard_pct")
    profile.barrel_pct  = stats.get("barrel_pct")

    # Recent form OBP windows
    profile.obp_15d = get_batter_recent_form(player_id, season, window=15)
    profile.obp_7d  = get_batter_recent_form(player_id, season, window=7)
    profile.obp_30d = get_batter_recent_form(player_id, season, window=30)

    # Pitch-type splits
    profile.vs_pitch_types = get_batter_vs_pitch_type(player_id, season)

    # Log missing critical fields
    for attr, label in [
        ("obp",   "OBP"),
        ("k_pct", "K%"),
        ("bb_pct","BB%"),
    ]:
        if getattr(profile, attr) is None:
            profile.missing_fields.append(label)

    return profile


def batter_reach_base_estimate(profile: BatterProfile) -> Optional[float]:
    """
    Estimate season-level OBP as proxy for reach-base probability.
    Preference: xOBP > OBP > xwOBA * 0.9.
    Returns None if no data.
    """
    if profile.xobp is not None:
        return profile.xobp
    if profile.obp is not None:
        return profile.obp
    if profile.xwoba is not None:
        return round(profile.xwoba * 0.85, 3)
    return None


def recent_form_trend(profile: BatterProfile) -> str:
    """Return 'improving', 'declining', 'neutral', or 'unknown'."""
    season_obp = profile.obp
    recent_obp = profile.obp_15d
    if season_obp is None or recent_obp is None:
        return "unknown"
    diff = recent_obp - season_obp
    if diff > 0.020:
        return "improving"
    if diff < -0.020:
        return "declining"
    return "neutral"
