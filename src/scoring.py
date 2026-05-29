"""
scoring.py – Pitcher Suppression Score and Batter Reach-Base Risk models.

All weights are defined in config.py.
No values are fabricated; missing data degrades the score gracefully.
"""

import logging
from typing import Optional

from config import SUPPRESSION_WEIGHTS, PARK_FACTORS, LINEUP_SPOT_WEIGHT
from src.pitcher_model import PitcherProfile, pitcher_recent_form_score
from src.batter_model  import BatterProfile, batter_reach_base_estimate, recent_form_trend
from src.utils import to_float, score_to_grade, reach_base_tier

logger = logging.getLogger(__name__)


# ─── Pitcher Suppression Score ────────────────────────────────────────────────

def compute_pitcher_suppression_score(
    pitcher:        PitcherProfile,
    opp_batters:    list[BatterProfile],
    venue:          str               = "Unknown Venue",
    weather_risk:   bool              = False,
    settings:       Optional[dict]    = None,
) -> dict:
    """
    Compute the composite pitcher suppression score (0–100).
    Returns a dict with:
        score, sub_scores, missing_penalties, grade, label
    """
    W = SUPPRESSION_WEIGHTS
    s = settings or {}
    use_park   = s.get("use_park_factor",   True)
    use_pitch  = s.get("use_pitch_matchup", True)
    use_zone   = s.get("use_zone_matchup",  True)
    use_weather= s.get("use_weather",       True)

    sub = {}

    # ── 1. Base-prevention skill (25%) ───────────────────────────────────────
    sub["base_prevention"] = _base_prevention_score(pitcher)

    # ── 2. Walk suppression (15%) ─────────────────────────────────────────────
    sub["walk_suppression"] = _walk_suppression_score(pitcher)

    # ── 3. Strikeout / whiff profile (15%) ───────────────────────────────────
    sub["strikeout_whiff"] = _so_whiff_score(pitcher)

    # ── 4. Recent form (10%) ──────────────────────────────────────────────────
    sub["recent_form"] = pitcher_recent_form_score(pitcher)

    # ── 5. Opponent weak-batter quality (15%) ────────────────────────────────
    sub["opponent_weakness"] = _opponent_weakness_score(opp_batters)

    # ── 6. Pitch-type matchup advantage (10%) ────────────────────────────────
    if use_pitch and pitcher.arsenal and opp_batters:
        sub["pitch_type_matchup"] = _pitch_type_matchup_score(pitcher, opp_batters)
    else:
        sub["pitch_type_matchup"] = 50.0  # neutral when unavailable

    # ── 7. Zone matchup advantage (5%) ───────────────────────────────────────
    # Approximated from chase / whiff data overlap
    if use_zone:
        sub["zone_matchup"] = _zone_matchup_score(pitcher, opp_batters)
    else:
        sub["zone_matchup"] = 50.0

    # ── 8. Context: park, weather (5%) ───────────────────────────────────────
    sub["context"] = _context_score(venue, weather_risk, use_park, use_weather)

    # ── Weighted total ────────────────────────────────────────────────────────
    total = 0.0
    for key, weight in W.items():
        total += sub.get(key, 50.0) * weight

    # Penalty for missing critical data
    penalty = 0.0
    if "pitch_arsenal" in pitcher.missing_fields:
        penalty += 5.0
    if "all_pitcher_stats" in pitcher.missing_fields:
        penalty += 15.0
    if not opp_batters:
        penalty += 10.0

    score = round(max(0.0, min(100.0, total - penalty)), 1)

    # Derive confidence grade
    has_confirmed = any(True for b in opp_batters)  # refined in matchup_model
    has_pitch     = bool(pitcher.arsenal)
    grade = score_to_grade(
        score,
        has_confirmed  = has_confirmed,
        has_pitch_data = has_pitch,
        pitcher_bb_pct = pitcher.bb_pct,
        batter_bb_pct  = None,
        weather_risk   = weather_risk,
    )

    from src.utils import score_band_label
    return {
        "score":     score,
        "sub_scores":sub,
        "penalty":   penalty,
        "grade":     grade,
        "label":     score_band_label(score),
    }


# ── Sub-score helpers ─────────────────────────────────────────────────────────

def _base_prevention_score(p: PitcherProfile) -> float:
    """
    Blend xFIP / FIP / ERA + xwOBA + OBP-allowed.
    Lower = better pitcher → higher score.
    """
    scores = []
    if p.xfip is not None:
        scores.append(max(0, min(100, (5.5 - p.xfip) / 4.5 * 100)))
    elif p.fip is not None:
        scores.append(max(0, min(100, (5.5 - p.fip) / 4.5 * 100)))
    elif p.era is not None:
        scores.append(max(0, min(100, (6.0 - p.era) / 5.0 * 100)))

    if p.xwoba_allowed is not None:
        # xwOBA: 0.250 elite → 100; 0.380 bad → 0
        scores.append(max(0, min(100, (0.380 - p.xwoba_allowed) / 0.130 * 100)))
    if p.obp_allowed is not None:
        scores.append(max(0, min(100, (0.380 - p.obp_allowed) / 0.130 * 100)))

    return round(sum(scores) / len(scores), 1) if scores else 50.0


def _walk_suppression_score(p: PitcherProfile) -> float:
    """BB% lower = better. League avg ~8.5%."""
    if p.bb_pct is None:
        return 50.0
    # 3% → 100, 15% → 0
    score = max(0.0, min(100.0, (15.0 - p.bb_pct) / 12.0 * 100))
    return round(score, 1)


def _so_whiff_score(p: PitcherProfile) -> float:
    """High K% and whiff% = better."""
    scores = []
    if p.k_pct is not None:
        # 15% → 0, 35% → 100
        scores.append(max(0, min(100, (p.k_pct - 15.0) / 20.0 * 100)))
    if p.whiff_pct is not None:
        # 18% → 0, 38% → 100
        scores.append(max(0, min(100, (p.whiff_pct - 18.0) / 20.0 * 100)))
    if p.csw_pct is not None:
        # 24% → 0, 38% → 100
        scores.append(max(0, min(100, (p.csw_pct - 24.0) / 14.0 * 100)))
    if p.k_bb_pct is not None:
        scores.append(max(0, min(100, (p.k_bb_pct + 5) / 25.0 * 100)))
    return round(sum(scores) / len(scores), 1) if scores else 50.0


def _opponent_weakness_score(batters: list[BatterProfile]) -> float:
    """
    Average reach-base estimate of lineup; invert it.
    Weaker lineup (lower avg OBP) → higher score for pitcher.
    """
    if not batters:
        return 40.0  # slight penalty for unknown lineup

    estimates = []
    for b in batters:
        est = batter_reach_base_estimate(b)
        if est is not None:
            # Weight by lineup spot exposure
            spot_w = LINEUP_SPOT_WEIGHT.get(b.lineup_spot, 1.0)
            estimates.append(est * spot_w)

    if not estimates:
        return 40.0

    avg_obp = sum(estimates) / len(estimates)
    # 0.250 → 100 (very weak lineup), 0.380 → 0 (strong lineup)
    score = max(0, min(100, (0.380 - avg_obp) / 0.130 * 100))
    return round(score, 1)


def _pitch_type_matchup_score(pitcher: PitcherProfile,
                               batters: list[BatterProfile]) -> float:
    """
    For each batter, look up their whiff_pct vs pitcher's top pitch.
    Average the advantage across the bottom 4 lineup batters (most targeted).
    """
    if not pitcher.arsenal:
        return 50.0

    # Sort pitches by usage
    top_pitches = sorted(pitcher.arsenal, key=lambda x: x.get("usage_pct") or 0, reverse=True)[:3]

    advantage_scores = []
    for b in batters:
        if not b.vs_pitch_types:
            continue
        for pitch in top_pitches:
            pt  = pitch.get("pitch_type", "?")
            bvp = b.vs_pitch_types.get(pt, {})
            batter_whiff = bvp.get("whiff_pct")
            batter_xwoba = bvp.get("xwoba")
            if batter_whiff is not None:
                # High batter whiff vs that pitch = advantage
                score = max(0, min(100, (batter_whiff - 15.0) / 30.0 * 100))
                advantage_scores.append(score)
            if batter_xwoba is not None:
                # Low batter xwOBA vs that pitch = advantage
                score = max(0, min(100, (0.380 - batter_xwoba) / 0.130 * 100))
                advantage_scores.append(score)

    return round(sum(advantage_scores) / len(advantage_scores), 1) if advantage_scores else 50.0


def _zone_matchup_score(pitcher: PitcherProfile,
                         batters: list[BatterProfile]) -> float:
    """
    Approximate zone advantage from pitcher chase_pct and batter chase_pct.
    High pitcher chase + high batter chase tendency = large advantage.
    """
    p_chase = pitcher.chase_pct
    if p_chase is None:
        return 50.0

    batter_chases = [b.chase_pct for b in batters if b.chase_pct is not None]
    if not batter_chases:
        return 50.0

    avg_batter_chase = sum(batter_chases) / len(batter_chases)
    combined = (p_chase + avg_batter_chase) / 2.0
    # 25% combined → 0, 45% combined → 100
    score = max(0, min(100, (combined - 25.0) / 20.0 * 100))
    return round(score, 1)


def _context_score(venue: str, weather_risk: bool,
                    use_park: bool, use_weather: bool) -> float:
    score = 50.0
    if use_park:
        pf = PARK_FACTORS.get(venue, 1.0)
        # pf 1.20 → pitcher unfavorable (-20), pf 0.90 → favorable (+15)
        score += (1.0 - pf) * 100
    if use_weather and weather_risk:
        score -= 15.0
    return round(max(0.0, min(100.0, score)), 1)


# ─── Batter Reach-Base Risk Model ─────────────────────────────────────────────

def compute_batter_reach_base_risk(
    batter:  BatterProfile,
    pitcher: PitcherProfile,
    venue:   str           = "Unknown Venue",
    weather_risk: bool     = False,
    lineup_confirmed: bool = False,
) -> dict:
    """
    Estimate this batter's probability of reaching base against this pitcher.
    Returns:
        walk_risk, hit_risk, hbp_risk, total_risk (0–1 floats),
        tier (Very Low … Very High), confidence_notes
    """
    notes = []

    # ── Walk risk ─────────────────────────────────────────────────────────────
    walk_risk = _walk_risk(batter, pitcher, notes)

    # ── Hit risk ──────────────────────────────────────────────────────────────
    hit_risk = _hit_risk(batter, pitcher, notes)

    # ── HBP risk ──────────────────────────────────────────────────────────────
    # League average HBP rate ~0.9%; adjust for pitcher BB% as proxy for command
    base_hbp = 0.009
    if pitcher.bb_pct is not None:
        base_hbp = pitcher.bb_pct / 100 * 0.10  # rough proxy
    hbp_risk = round(min(0.04, base_hbp), 4)

    # ── Total (can't simply add – correlated) ─────────────────────────────────
    # Approximate: P(reach) ≈ 1 - P(not walk) * P(not hit) * P(not HBP)
    total_risk = round(1.0 - (1 - walk_risk) * (1 - hit_risk) * (1 - hbp_risk), 4)
    total_risk = max(0.0, min(1.0, total_risk))

    # ── Park / weather adjustment ──────────────────────────────────────────────
    pf = PARK_FACTORS.get(venue, 1.0)
    total_risk = round(min(1.0, total_risk * (0.85 + 0.15 * pf)), 4)
    if weather_risk:
        total_risk = round(min(1.0, total_risk * 1.05), 4)
        notes.append("Weather risk slightly increases uncertainty.")

    # ── Recent form adjustment ────────────────────────────────────────────────
    trend = recent_form_trend(batter)
    if trend == "declining":
        total_risk = round(total_risk * 0.95, 4)
        notes.append("Batter in declining recent form – reach-base risk reduced slightly.")
    elif trend == "improving":
        total_risk = round(min(1.0, total_risk * 1.05), 4)
        notes.append("Batter in improving recent form – reach-base risk slightly higher.")

    tier = reach_base_tier(total_risk)

    # Confidence grade for this batter target
    grade = score_to_grade(
        score          = (1.0 - total_risk) * 100,
        has_confirmed  = lineup_confirmed,
        has_pitch_data = bool(pitcher.arsenal) and bool(batter.vs_pitch_types),
        pitcher_bb_pct = pitcher.bb_pct,
        batter_bb_pct  = batter.bb_pct,
        weather_risk   = weather_risk,
    )

    if "all_batter_stats" in batter.missing_fields:
        notes.append("⚠️ Batter stats unavailable – estimate based on lineup position only.")
    if "player_id_unresolved" in batter.missing_fields:
        notes.append("⚠️ Player ID unresolved – stats could not be fetched.")
    if not batter.vs_pitch_types:
        notes.append("⚠️ Pitch-type splits unavailable – confidence reduced.")

    return {
        "batter_name":  batter.name,
        "lineup_spot":  batter.lineup_spot,
        "bats":         batter.bats,
        "walk_risk":    walk_risk,
        "hit_risk":     hit_risk,
        "hbp_risk":     hbp_risk,
        "total_risk":   total_risk,
        "tier":         tier,
        "grade":        grade,
        "trend":        trend,
        "notes":        notes,
        "missing":      batter.missing_fields,
    }


def _walk_risk(batter: BatterProfile, pitcher: PitcherProfile, notes: list) -> float:
    """
    Estimate P(walk).
    Base = batter BB% / 100; adjust for pitcher BB%.
    """
    b_bb = (batter.bb_pct or 8.5) / 100.0
    p_bb = (pitcher.bb_pct or 8.5) / 100.0
    # Blend: 60% batter, 40% pitcher walk rates
    raw  = 0.60 * b_bb + 0.40 * p_bb
    if batter.bb_pct is None:
        notes.append("Batter BB% missing – league average used.")
    if pitcher.bb_pct is None:
        notes.append("Pitcher BB% missing – league average used.")
    return round(max(0.0, min(0.25, raw)), 4)


def _hit_risk(batter: BatterProfile, pitcher: PitcherProfile, notes: list) -> float:
    """
    Estimate P(hit) in a PA.
    Use batter xBA; adjust for pitcher xwOBA_allowed / hard_pct.
    """
    # Start from batter xBA or AVG
    b_avg = batter.xba or batter.avg or 0.250
    # Pitcher resistance multiplier
    if pitcher.xwoba_allowed is not None:
        # League avg xwOBA ~0.315; pitcher below that → reduces hit chance
        pitcher_multiplier = pitcher.xwoba_allowed / 0.315
    else:
        pitcher_multiplier = 1.0
    raw = b_avg * pitcher_multiplier
    # Strikeout adjustment: high K% batter hits less often
    if batter.k_pct is not None:
        raw *= (1.0 - (batter.k_pct / 100.0) * 0.5)
    return round(max(0.0, min(0.45, raw)), 4)
