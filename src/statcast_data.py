"""
statcast_data.py – Pull pitcher and batter Statcast/Baseball Savant data.

Uses pybaseball (which wraps Baseball Savant CSV endpoints).
Falls back to direct URL fetch if pybaseball is unavailable.

Key functions:
  get_pitcher_statcast(player_id, season) -> dict
  get_batter_statcast(player_id, season)  -> dict
  get_pitch_arsenal(player_id, season)    -> list[dict]
"""

import io
import logging
from typing import Optional

import pandas as pd

from src.cache import cache_get, cache_set
from src.utils import safe_get_text, to_float

logger = logging.getLogger(__name__)

# Try to import pybaseball; flag if missing
try:
    import pybaseball as pb
    pb.cache.enable()
    _HAS_PYBASEBALL = True
    logger.info("pybaseball available")
except ImportError:
    _HAS_PYBASEBALL = False
    logger.warning("pybaseball not installed – falling back to direct Savant CSV fetch")


# ─── Pitcher Statcast summary ─────────────────────────────────────────────────

def get_pitcher_statcast(player_id: int, season: int) -> dict:
    """Return dict of pitcher-level Statcast stats for *season*."""
    cache_key = f"pitcher_statcast_{player_id}_{season}"
    cached = cache_get(cache_key, "statcast")
    if cached is not None:
        return cached

    data: dict = {}

    # ── Try pybaseball pitching stats table ──────────────────────────────────
    if _HAS_PYBASEBALL:
        try:
            df = pb.pitching_stats(season, season, qual=0)
            row = df[df["IDfg"].astype(str) == str(player_id)] if "IDfg" in df.columns else pd.DataFrame()
            if row.empty:
                row = _fangraphs_row_by_mlbam(df, player_id)
            if not row.empty:
                r    = row.iloc[0]
                data = _extract_pitcher_fangraphs(r)
        except Exception as exc:
            logger.debug("pybaseball pitcher stats (FanGraphs) unavailable for %d: %s", player_id, exc)

    # ── Savant pitcher dashboard (leaderboard CSV) ───────────────────────────
    savant_data = _savant_pitcher_dashboard(player_id, season)
    data.update({k: v for k, v in savant_data.items() if v is not None})

    cache_set(cache_key, data)
    return data


def _fangraphs_row_by_mlbam(df: pd.DataFrame, mlbam_id: int) -> pd.DataFrame:
    """Try to cross-reference FanGraphs data via playerid_lookup."""
    if not _HAS_PYBASEBALL:
        return pd.DataFrame()
    try:
        from pybaseball import playerid_reverse_lookup
        lu = playerid_reverse_lookup([mlbam_id], key_type="mlbam")
        if lu.empty:
            return pd.DataFrame()
        fg_id = lu.iloc[0].get("key_fangraphs")
        if fg_id and "IDfg" in df.columns:
            row = df[df["IDfg"].astype(str) == str(fg_id)]
            return row
    except Exception as exc:
        logger.debug("playerid_reverse_lookup failed: %s", exc)
    return pd.DataFrame()


def _extract_pitcher_fangraphs(r: pd.Series) -> dict:
    """Map FanGraphs column names to our internal keys."""
    def g(col):
        return to_float(r.get(col))

    return {
        "era":        g("ERA"),
        "fip":        g("FIP"),
        "xfip":       g("xFIP"),
        "siera":      g("SIERA"),
        "whip":       g("WHIP"),
        "k_pct":      g("K%"),
        "bb_pct":     g("BB%"),
        "k_bb_pct":   g("K-BB%"),
        "hr9":        g("HR/9"),
        "gb_pct":     g("GB%"),
        "hard_pct":   g("Hard%"),
        "csw_pct":    g("CSW%"),
        "innings":    g("IP"),
        "games":      g("G"),
        "whiff_pct":  g("Whiff%"),
        "chase_pct":  g("O-Swing%"),
    }


def _savant_pitcher_dashboard(player_id: int, season: int) -> dict:
    """
    Pull pitcher-level Statcast leaderboard from Baseball Savant.
    Endpoint: /leaderboard/custom?player_type=pitcher&...
    """
    url    = "https://baseballsavant.mlb.com/leaderboard/custom"
    params = {
        "year":        season,
        "type":        "pitcher",
        "filter":      "",
        "min":         "1",
        "selections":  "xwoba,xera,xba,launch_speed,barrel_batted_rate,k_percent,bb_percent,whiff_percent,on_base_percent,p_formatted_ip",
        "chart":       "false",
        "x":           "xwoba",
        "y":           "xwoba",
        "r":           "no",
        "csv":         "true",
        "player_id":   player_id,
    }
    csv_text = safe_get_text(url, params)
    if not csv_text or len(csv_text) < 50:
        return {}
    try:
        df  = pd.read_csv(io.StringIO(csv_text))
        df  = df[df["player_id"].astype(str) == str(player_id)]
        if df.empty:
            return {}
        r   = df.iloc[0]
        return {
            "xwoba_allowed":   to_float(r.get("xwoba")),
            "xera":            to_float(r.get("xera")),
            "xba_allowed":     to_float(r.get("xba")),
            "barrel_rate":     to_float(r.get("barrel_batted_rate")),
            "k_pct_savant":    to_float(r.get("k_percent")),
            "bb_pct_savant":   to_float(r.get("bb_percent")),
            "whiff_pct_savant":to_float(r.get("whiff_percent")),
            "obp_allowed":     to_float(r.get("on_base_percent")),
            "ip_savant":       to_float(r.get("p_formatted_ip")),
        }
    except Exception as exc:
        logger.warning("Savant pitcher dashboard parse error for %d: %s", player_id, exc)
        return {}


# ─── Pitch Arsenal ────────────────────────────────────────────────────────────

def get_pitch_arsenal(player_id: int, season: int) -> list[dict]:
    """Return list of pitch-type dicts for *player_id*."""
    cache_key = f"arsenal_{player_id}_{season}"
    cached = cache_get(cache_key, "statcast")
    if cached is not None:
        return cached

    arsenal = _savant_pitch_arsenal(player_id, season)
    cache_set(cache_key, arsenal)
    return arsenal


def _savant_pitch_arsenal(player_id: int, season: int) -> list[dict]:
    """
    Baseball Savant pitch arsenal leaderboard filtered to one pitcher.
    https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats
    """
    url    = "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"
    params = {
        "type":      "pitcher",
        "pitchType": "na",
        "year":      season,
        "position":  "1",
        "team":      "",
        "min":       "1",
        "csv":       "true",
    }
    csv_text = safe_get_text(url, params)
    if not csv_text or len(csv_text) < 50:
        logger.warning("Savant pitch arsenal unavailable for %d", player_id)
        return []
    try:
        df = pd.read_csv(io.StringIO(csv_text))
        # Column name may vary: 'pitcher_id' or 'player_id'
        id_col = "pitcher_id" if "pitcher_id" in df.columns else "player_id"
        if id_col not in df.columns:
            logger.warning("Arsenal CSV missing ID column; cols=%s", list(df.columns[:8]))
            return []
        df = df[df[id_col].astype(str) == str(player_id)]
        pitches = []
        for _, row in df.iterrows():
            pitches.append({
                "pitch_type":   row.get("pitch_type", "?"),
                "pitch_name":   row.get("pitch_name", "?"),
                "usage_pct":    to_float(row.get("pitch_usage") or row.get("pitch_percent")),
                "velocity":     to_float(row.get("avg_speed")   or row.get("release_speed")),
                "whiff_pct":    to_float(row.get("whiff_percent")),
                "chase_pct":    to_float(row.get("chase_percent")),
                "xwoba":        to_float(row.get("xwoba")),
                "run_value":    to_float(row.get("run_value_per_100") or row.get("run_value")),
                "k_pct":        to_float(row.get("k_percent")),
            })
        return pitches
    except Exception as exc:
        logger.warning("Arsenal parse error for %d: %s", player_id, exc)
        return []


# ─── Batter Statcast summary ─────────────────────────────────────────────────

def get_batter_statcast(player_id: int, season: int) -> dict:
    """Return dict of batter-level Statcast stats for *season*."""
    cache_key = f"batter_statcast_{player_id}_{season}"
    cached = cache_get(cache_key, "statcast")
    if cached is not None:
        return cached

    data: dict = {}

    if _HAS_PYBASEBALL:
        try:
            df  = pb.batting_stats(season, season, qual=0)
            row = df[df["IDfg"].astype(str) == str(player_id)] if "IDfg" in df.columns else pd.DataFrame()
            if row.empty:
                row = _fangraphs_row_by_mlbam(df, player_id)
            if not row.empty:
                data = _extract_batter_fangraphs(row.iloc[0])
        except Exception as exc:
            logger.debug("pybaseball batter stats (FanGraphs) unavailable for %d: %s", player_id, exc)

    savant_data = _savant_batter_dashboard(player_id, season)
    data.update({k: v for k, v in savant_data.items() if v is not None})

    cache_set(cache_key, data)
    return data


def _extract_batter_fangraphs(r: pd.Series) -> dict:
    def g(col):
        return to_float(r.get(col))
    return {
        "obp":        g("OBP"),
        "avg":        g("AVG"),
        "k_pct":      g("K%"),
        "bb_pct":     g("BB%"),
        "hard_pct":   g("Hard%"),
        "barrel_pct": g("Barrel%"),
        "chase_pct":  g("O-Swing%"),
        "whiff_pct":  g("SwStr%"),
        "contact_pct":g("Contact%"),
        "woba":       g("wOBA"),
        "ops":        g("OPS"),
        "iso":        g("ISO"),
    }


def _savant_batter_dashboard(player_id: int, season: int) -> dict:
    url    = "https://baseballsavant.mlb.com/leaderboard/custom"
    params = {
        "year":        season,
        "type":        "batter",
        "filter":      "",
        "min":         "1",
        "selections":  "xwoba,xba,launch_speed,barrel_batted_rate,k_percent,bb_percent,whiff_percent,on_base_percent,xobp",
        "chart":       "false",
        "csv":         "true",
        "player_id":   player_id,
    }
    csv_text = safe_get_text(url, params)
    if not csv_text or len(csv_text) < 50:
        return {}
    try:
        df  = pd.read_csv(io.StringIO(csv_text))
        df  = df[df["player_id"].astype(str) == str(player_id)]
        if df.empty:
            return {}
        r   = df.iloc[0]
        return {
            "xwoba":       to_float(r.get("xwoba")),
            "xba":         to_float(r.get("xba")),
            "xobp":        to_float(r.get("xobp")),
            "barrel_pct":  to_float(r.get("barrel_batted_rate")),
            "k_pct":       to_float(r.get("k_percent")),
            "bb_pct":      to_float(r.get("bb_percent")),
            "whiff_pct":   to_float(r.get("whiff_percent")),
            "obp":         to_float(r.get("on_base_percent")),
        }
    except Exception as exc:
        logger.warning("Savant batter dashboard parse error for %d: %s", player_id, exc)
        return {}


# ─── Batter vs pitch-type splits ─────────────────────────────────────────────

def get_batter_vs_pitch_type(player_id: int, season: int) -> dict[str, dict]:
    """
    Return {pitch_type: {whiff_pct, xwoba, k_pct}} for a batter.
    Uses Baseball Savant batter pitch-type splits.
    """
    cache_key = f"batter_vs_pitch_{player_id}_{season}"
    cached = cache_get(cache_key, "statcast")
    if cached is not None:
        return cached

    url    = "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"
    params = {
        "type":      "batter",
        "pitchType": "na",
        "year":      season,
        "position":  "0",
        "team":      "",
        "min":       "1",
        "csv":       "true",
    }
    csv_text = safe_get_text(url, params)
    result: dict[str, dict] = {}
    if not csv_text or len(csv_text) < 50:
        return result
    try:
        df = pd.read_csv(io.StringIO(csv_text))
        id_col = "batter_id" if "batter_id" in df.columns else "player_id"
        if id_col not in df.columns:
            return result
        df = df[df[id_col].astype(str) == str(player_id)]
        for _, row in df.iterrows():
            pt = str(row.get("pitch_type", "?"))
            result[pt] = {
                "whiff_pct": to_float(row.get("whiff_percent")),
                "xwoba":     to_float(row.get("xwoba")),
                "k_pct":     to_float(row.get("k_percent")),
                "chase_pct": to_float(row.get("chase_percent")),
            }
    except Exception as exc:
        logger.warning("Batter vs pitch type error for %d: %s", player_id, exc)

    cache_set(cache_key, result)
    return result


# ─── Recent form (last N games rolling OBP) ──────────────────────────────────

def get_batter_recent_form(player_id: int, season: int, window: int = 15) -> Optional[float]:
    """
    Return rolling OBP over last *window* plate appearances.
    Uses pybaseball statcast batter pull if available.
    Returns None if data unavailable.
    """
    if not _HAS_PYBASEBALL:
        return None
    cache_key = f"batter_recent_{player_id}_{season}_{window}"
    cached = cache_get(cache_key, "statcast")
    if cached is not None:
        return cached

    try:
        from datetime import date, timedelta
        end   = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=window + 5)).strftime("%Y-%m-%d")
        df    = pb.statcast_batter(start, end, player_id=player_id)
        if df is None or df.empty:
            return None
        # compute rough OBP from events in window
        on_base_events = {"single", "double", "triple", "home_run",
                          "walk", "hit_by_pitch", "intent_walk"}
        plate_apps     = df[df["events"].notna()]
        if len(plate_apps) == 0:
            return None
        recent      = plate_apps.tail(window)
        on_base_cnt = recent["events"].isin(on_base_events).sum()
        obp         = round(on_base_cnt / len(recent), 3)
        cache_set(cache_key, obp)
        return obp
    except Exception as exc:
        logger.warning("Recent form error for %d: %s", player_id, exc)
        return None
