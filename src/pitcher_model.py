"""
pitcher_model.py – Build the PitcherProfile dataclass from raw stat dicts.

A PitcherProfile holds every stat the scoring model needs, with None
where data is unavailable (never fabricated).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.statcast_data import get_pitcher_statcast, get_pitch_arsenal
from src.player_ids import get_player_info

logger = logging.getLogger(__name__)


@dataclass
class PitcherProfile:
    # Identity
    player_id:    int
    name:         str
    team:         str
    throws:       Optional[str]   = None  # "R" / "L"

    # Traditional stats
    era:          Optional[float] = None
    fip:          Optional[float] = None
    xfip:         Optional[float] = None
    xera:         Optional[float] = None
    siera:        Optional[float] = None
    whip:         Optional[float] = None
    obp_allowed:  Optional[float] = None

    # Sabermetrics
    xwoba_allowed: Optional[float] = None
    k_pct:         Optional[float] = None  # raw % e.g. 22.5
    bb_pct:        Optional[float] = None
    k_bb_pct:      Optional[float] = None
    csw_pct:       Optional[float] = None
    whiff_pct:     Optional[float] = None
    chase_pct:     Optional[float] = None
    hard_pct:      Optional[float] = None
    barrel_rate:   Optional[float] = None
    gb_pct:        Optional[float] = None

    # Context
    innings:       Optional[float] = None
    games:         Optional[int]   = None

    # Pitch arsenal [{pitch_type, usage_pct, velocity, whiff_pct, ...}]
    arsenal:       list[dict]      = field(default_factory=list)

    # Data quality flags
    missing_fields: list[str]     = field(default_factory=list)


def build_pitcher_profile(player_id: int, name: str, team: str,
                           throws: Optional[str], season: int) -> PitcherProfile:
    """Construct a PitcherProfile from MLB Stats API + Statcast data."""
    profile = PitcherProfile(player_id=player_id, name=name, team=team, throws=throws)

    # ── Statcast / Savant stats ───────────────────────────────────────────────
    stats = get_pitcher_statcast(player_id, season)
    if not stats:
        logger.warning("No Statcast data for pitcher %s (%d)", name, player_id)
        profile.missing_fields.append("all_pitcher_stats")
        return profile

    profile.era          = stats.get("era")
    profile.fip          = stats.get("fip")
    profile.xfip         = stats.get("xfip")
    profile.xera         = stats.get("xera")
    profile.siera        = stats.get("siera")
    profile.whip         = stats.get("whip")
    profile.obp_allowed  = stats.get("obp_allowed")
    profile.xwoba_allowed= stats.get("xwoba_allowed")
    profile.k_pct        = stats.get("k_pct") or stats.get("k_pct_savant")
    profile.bb_pct       = stats.get("bb_pct") or stats.get("bb_pct_savant")
    profile.k_bb_pct     = stats.get("k_bb_pct")
    profile.csw_pct      = stats.get("csw_pct")
    profile.whiff_pct    = stats.get("whiff_pct") or stats.get("whiff_pct_savant")
    profile.chase_pct    = stats.get("chase_pct")
    profile.hard_pct     = stats.get("hard_pct")
    profile.barrel_rate  = stats.get("barrel_rate")
    profile.gb_pct       = stats.get("gb_pct")
    profile.innings      = stats.get("innings") or stats.get("ip_savant")
    profile.games        = stats.get("games")

    # Compute k_bb_pct if missing
    if profile.k_bb_pct is None and profile.k_pct is not None and profile.bb_pct is not None:
        profile.k_bb_pct = round(profile.k_pct - profile.bb_pct, 1)

    # ── Pitch arsenal ─────────────────────────────────────────────────────────
    profile.arsenal = get_pitch_arsenal(player_id, season)
    if not profile.arsenal:
        profile.missing_fields.append("pitch_arsenal")

    # ── Log missing critical fields ───────────────────────────────────────────
    for attr, label in [
        ("era",         "ERA"),
        ("k_pct",       "K%"),
        ("bb_pct",      "BB%"),
        ("whiff_pct",   "Whiff%"),
        ("obp_allowed", "OBP_allowed"),
    ]:
        if getattr(profile, attr) is None:
            profile.missing_fields.append(label)
            logger.warning("Missing %s for pitcher %s", label, name)

    return profile


def pitcher_recent_form_score(profile: PitcherProfile) -> float:
    """
    Derive a 0–100 recent-form sub-score from ERA/FIP/xFIP.
    Lower ERA/FIP = higher score.
    Returns 50.0 (neutral) if data unavailable.
    """
    # Use xFIP > FIP > ERA in order of preference
    metric = profile.xfip or profile.fip or profile.era
    if metric is None:
        return 50.0
    # Map: ERA 1.0 → 100, ERA 6.0+ → 0
    score = max(0.0, min(100.0, (6.0 - metric) / 5.0 * 100))
    return round(score, 1)
