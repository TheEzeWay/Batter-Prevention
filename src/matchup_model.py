"""
matchup_model.py – Assemble full game matchups and produce ranked output.

MatchupResult is the main output object per game/pitcher side.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from config import DEFAULT_TOP_PITCHERS, DEFAULT_TOP_TARGETS, PARK_FACTORS
from src.mlb_schedule    import fetch_schedule
from src.lineups         import fetch_lineups_for_game
from src.player_ids      import get_player_info, resolve_roster_ids
from src.pitcher_model   import build_pitcher_profile, PitcherProfile
from src.batter_model    import build_batter_profile, BatterProfile, batter_reach_base_estimate
from src.statcast_data   import get_pitcher_statcast, get_pitch_arsenal
from src.weather         import fetch_weather
from src.scoring         import compute_pitcher_suppression_score, compute_batter_reach_base_risk
from src.utils           import score_to_grade, reach_base_tier

logger = logging.getLogger(__name__)


@dataclass
class BatterRiskResult:
    batter_name:  str
    lineup_spot:  int
    bats:         Optional[str]
    walk_risk:    float
    hit_risk:     float
    hbp_risk:     float
    total_risk:   float
    tier:         str
    grade:        str
    trend:        str
    notes:        list[str]
    missing:      list[str]


@dataclass
class MatchupResult:
    # Pitcher side
    pitcher_id:     int
    pitcher_name:   str
    pitcher_team:   str
    pitcher_hand:   Optional[str]
    opponent_team:  str
    game_time_utc:  str
    venue:          str
    park_factor:    float

    # Pitcher suppression
    suppression_score:  float
    suppression_label:  str
    suppression_grade:  str
    suppression_subs:   dict

    # Lineup status
    lineup_status:  str   # "confirmed" / "projected" / "unavailable"

    # Batter risk results (all batters, sorted by lowest risk)
    batter_risks:   list[BatterRiskResult] = field(default_factory=list)

    # Top N targets (lowest reach-base risk)
    top_targets:    list[BatterRiskResult] = field(default_factory=list)

    # Pitch-type matchup notes
    pitch_matchup_notes: list[dict] = field(default_factory=list)

    # Weather
    weather:        dict = field(default_factory=dict)

    # Data warnings
    warnings:       list[str] = field(default_factory=list)


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    game_date:   date,
    settings:    Optional[dict] = None,
    progress_cb: Optional[object] = None,  # callable(msg)
) -> tuple[list[MatchupResult], dict]:
    """
    Full data pipeline for a given date.
    Returns (ranked_matchups, slate_overview).
    """
    s = settings or {}
    season = game_date.year

    def _progress(msg: str):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    # ── Step 1: Schedule ─────────────────────────────────────────────────────
    _progress("Loading today's MLB slate...")
    games = fetch_schedule(game_date)
    if not games:
        return [], {"error": "No MLB games found for this date.", "games": []}

    # ── Step 2: Lineups ───────────────────────────────────────────────────────
    _progress("Fetching lineups...")

    # ── Step 3: Pitcher stats ─────────────────────────────────────────────────
    _progress("Pulling pitcher stats...")

    # ── Step 4: Batter stats ──────────────────────────────────────────────────
    _progress("Pulling batter stats...")

    all_matchups: list[MatchupResult] = []

    # ── Build all matchups in parallel (thread pool) ────────────────────────
    from concurrent.futures import ThreadPoolExecutor, as_completed
    tasks = [(g, side) for g in games for side in ("away", "home")]
    max_workers = min(8, len(tasks))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_build_matchup, g, side, season, s, _progress): (g, side)
            for g, side in tasks
        }
        for fut in as_completed(futures):
            try:
                matchup = fut.result()
                if matchup:
                    all_matchups.append(matchup)
            except Exception as exc:
                g, side = futures[fut]
                logger.warning("Matchup build failed for %s %s: %s",
                               g.get("game_pk"), side, exc)

    # ── Step 5: Scoring ───────────────────────────────────────────────────────
    _progress("Calculating pitcher suppression scores...")
    _progress("Calculating batter reach-base risks...")

    # ── Step 6: Rank ──────────────────────────────────────────────────────────
    _progress("Ranking matchups...")
    ranked = sorted(all_matchups, key=lambda m: m.suppression_score, reverse=True)

    # ── Slate overview ────────────────────────────────────────────────────────
    n_confirmed  = sum(1 for m in ranked if m.lineup_status == "confirmed")
    n_projected  = sum(1 for m in ranked if m.lineup_status == "projected")
    n_unavail    = sum(1 for m in ranked if m.lineup_status == "unavailable")
    weather_warn = [m.pitcher_name + " @ " + m.venue
                    for m in ranked if m.weather.get("risk_flag")]

    overview = {
        "date":               str(game_date),
        "total_games":        len(games),
        "total_matchups":     len(ranked),
        "confirmed_lineups":  n_confirmed,
        "projected_lineups":  n_projected,
        "unavailable_lineups":n_unavail,
        "weather_concerns":   weather_warn,
        "games":              games,
    }

    _progress("Generating final report...")
    return ranked, overview


def _build_matchup(game: dict, side: str, season: int,
                    settings: dict, progress: object) -> Optional[MatchupResult]:
    """Build a MatchupResult for one pitcher (away or home) in a game."""

    if side == "away":
        pitcher_name = game.get("away_pitcher")
        pitcher_id   = game.get("away_pitcher_id")
        pitcher_hand = game.get("away_pitcher_hand")
        pitcher_team = game.get("away_team")
        opp_team_id  = game.get("home_team_id")
        opp_team     = game.get("home_team")
        opp_side     = "home"
    else:
        pitcher_name = game.get("home_pitcher")
        pitcher_id   = game.get("home_pitcher_id")
        pitcher_hand = game.get("home_pitcher_hand")
        pitcher_team = game.get("home_team")
        opp_team_id  = game.get("away_team_id")
        opp_team     = game.get("away_team")
        opp_side     = "away"

    if not pitcher_name or not pitcher_id:
        logger.warning("No probable pitcher for %s side of game %s", side, game.get("game_pk"))
        return None

    venue      = game.get("venue", "Unknown Venue")
    game_pk    = game.get("game_pk")
    game_time  = game.get("game_time_utc", "")
    park_factor = PARK_FACTORS.get(venue, 1.0)

    # ── Pitcher profile ───────────────────────────────────────────────────────
    pitcher = build_pitcher_profile(pitcher_id, pitcher_name, pitcher_team,
                                    pitcher_hand, season)

    # ── Lineup ───────────────────────────────────────────────────────────────
    lineups   = fetch_lineups_for_game(
        game_pk,
        game.get("away_team_id"), game.get("home_team_id"),
        game.get("away_team"),    game.get("home_team"),
        date.today(),
    )
    opp_lineup = lineups.get(opp_side, {})
    lineup_status = opp_lineup.get("status", "unavailable")

    # ── Batter profiles ───────────────────────────────────────────────────────
    batter_profiles: list[BatterProfile] = []
    for player_entry in opp_lineup.get("players", []):
        bp = build_batter_profile(
            player_id  = player_entry.get("player_id"),
            name       = player_entry.get("player_name", "Unknown"),
            team       = opp_team,
            lineup_spot= player_entry.get("lineup_spot", 0),
            bats       = player_entry.get("bats"),
            position   = player_entry.get("position"),
            season     = season,
        )
        batter_profiles.append(bp)

    # If lineup unavailable, try to use roster as fallback (no order)
    if not batter_profiles and opp_team_id:
        logger.warning("Lineup unavailable for %s – falling back to roster", opp_team)
        batter_profiles = _roster_fallback(opp_team_id, opp_team, season)
        if batter_profiles:
            lineup_status = "projected"

    # ── Weather ───────────────────────────────────────────────────────────────
    weather_info = {}
    if settings.get("use_weather", True):
        weather_info = fetch_weather(venue, game_time)
    weather_risk = weather_info.get("risk_flag", False)

    # ── Suppression score ─────────────────────────────────────────────────────
    supp = compute_pitcher_suppression_score(
        pitcher      = pitcher,
        opp_batters  = batter_profiles,
        venue        = venue,
        weather_risk = weather_risk,
        settings     = settings,
    )

    # Refine grade based on actual lineup confirmation
    from src.utils import score_to_grade
    confirmed = lineup_status == "confirmed"
    grade = score_to_grade(
        score          = supp["score"],
        has_confirmed  = confirmed,
        has_pitch_data = bool(pitcher.arsenal),
        pitcher_bb_pct = pitcher.bb_pct,
        batter_bb_pct  = None,
        weather_risk   = weather_risk,
    )

    # ── Batter risk results ───────────────────────────────────────────────────
    batter_risks: list[BatterRiskResult] = []
    for b in batter_profiles:
        risk = compute_batter_reach_base_risk(
            batter   = b,
            pitcher  = pitcher,
            venue    = venue,
            weather_risk = weather_risk,
            lineup_confirmed = confirmed,
        )
        batter_risks.append(BatterRiskResult(**risk))

    # Sort: lowest total_risk first (weakest reach-base batters first)
    batter_risks.sort(key=lambda x: x.total_risk)

    top_n = settings.get("top_targets", 4)
    top_targets = batter_risks[:top_n]

    # ── Pitch matchup notes ───────────────────────────────────────────────────
    pitch_notes = _build_pitch_notes(pitcher, batter_risks[:top_n])

    # ── Warnings ─────────────────────────────────────────────────────────────
    warnings = []
    if lineup_status == "projected":
        warnings.append("⚠️ Lineup is PROJECTED. Rerun after confirmed lineups release.")
    if lineup_status == "unavailable":
        warnings.append("⚠️ Lineup unavailable. Confidence reduced.")
    if pitcher.missing_fields:
        warnings.append(f"Missing pitcher data: {', '.join(pitcher.missing_fields)}")
    if weather_risk:
        warnings.append(f"⚠️ Weather risk: {weather_info.get('risk')} at {venue}")

    return MatchupResult(
        pitcher_id         = pitcher_id,
        pitcher_name       = pitcher_name,
        pitcher_team       = pitcher_team,
        pitcher_hand       = pitcher_hand,
        opponent_team      = opp_team,
        game_time_utc      = game_time,
        venue              = venue,
        park_factor        = park_factor,
        suppression_score  = supp["score"],
        suppression_label  = supp["label"],
        suppression_grade  = grade,
        suppression_subs   = supp["sub_scores"],
        lineup_status      = lineup_status,
        batter_risks       = batter_risks,
        top_targets        = top_targets,
        pitch_matchup_notes= pitch_notes,
        weather            = weather_info,
        warnings           = warnings,
    )


def _roster_fallback(team_id: int, team_name: str, season: int) -> list[BatterProfile]:
    """Use team roster as projected lineup when no lineup is available."""
    roster = resolve_roster_ids(team_id)
    profiles = []
    spot = 1
    for name, pid in list(roster.items())[:9]:
        bp = build_batter_profile(
            player_id=pid, name=name, team=team_name,
            lineup_spot=spot, bats=None, position=None, season=season,
        )
        profiles.append(bp)
        spot += 1
    return profiles


def _build_pitch_notes(pitcher: PitcherProfile,
                        targets: list[BatterRiskResult]) -> list[dict]:
    """Build pitch-type vs batter-weakness notes for the top targets."""
    if not pitcher.arsenal:
        return []

    top_pitches = sorted(pitcher.arsenal, key=lambda x: x.get("usage_pct") or 0, reverse=True)[:3]
    notes = []
    for tr in targets:
        for pitch in top_pitches:
            pt   = pitch.get("pitch_type", "?")
            pname= pitch.get("pitch_name", pt)
            usage= pitch.get("usage_pct")
            p_whiff = pitch.get("whiff_pct")
            notes.append({
                "pitcher":          pitcher.name,
                "target_batter":    tr.batter_name,
                "pitch_type":       pt,
                "pitch_name":       pname,
                "usage_pct":        usage,
                "pitcher_whiff_pct":p_whiff,
                "pitcher_xwoba":    pitch.get("xwoba"),
                "edge_rating":      _edge_label(p_whiff),
            })
    return notes


def _edge_label(whiff: Optional[float]) -> str:
    if whiff is None:
        return "Unknown"
    if whiff >= 35:
        return "Elite"
    if whiff >= 28:
        return "Strong"
    if whiff >= 22:
        return "Moderate"
    return "Weak"
