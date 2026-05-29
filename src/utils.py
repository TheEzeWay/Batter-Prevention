"""
utils.py – Shared helpers: HTTP, type coercion, formatting, logging setup.
"""

import logging
import time
from typing import Any, Optional

import requests

from config import MLB_REQUEST_TIMEOUT, MLB_RATE_LIMIT_PAUSE

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def safe_get(url: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict]:
    """GET JSON from *url* with retry / back-off.  Returns None on failure."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=MLB_REQUEST_TIMEOUT)
            r.raise_for_status()
            time.sleep(MLB_RATE_LIMIT_PAUSE)
            return r.json()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                wait = 2 ** attempt
                logger.warning("Rate-limited on %s – sleeping %ss", url, wait)
                time.sleep(wait)
            else:
                logger.warning("HTTP error on %s (attempt %d): %s", url, attempt, exc)
                break
        except Exception as exc:
            logger.warning("Request error on %s (attempt %d): %s", url, attempt, exc)
            if attempt < retries:
                time.sleep(1.5 * attempt)
    return None


def safe_get_text(url: str, params: Optional[dict] = None, retries: int = 3) -> Optional[str]:
    """GET raw text (CSV, HTML) from *url*."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=MLB_REQUEST_TIMEOUT,
                             headers={"User-Agent": "MLB-Suppression-Dashboard/1.0"})
            r.raise_for_status()
            time.sleep(MLB_RATE_LIMIT_PAUSE)
            return r.text
        except Exception as exc:
            logger.warning("Text request error on %s (attempt %d): %s", url, attempt, exc)
            if attempt < retries:
                time.sleep(1.5 * attempt)
    return None


def to_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Coerce *val* to float, return *default* on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def to_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def pct_to_float(val: Any) -> Optional[float]:
    """Convert '12.3%' or 12.3 to 12.3 (raw %, not decimal)."""
    if val is None:
        return None
    s = str(val).strip().rstrip("%")
    return to_float(s)


def fmt_pct(val: Optional[float], decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}%"


def fmt_stat(val: Optional[float], decimals: int = 3) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}"


def hand_label(hand: Optional[str]) -> str:
    if not hand:
        return "?"
    h = hand.upper()
    return {"R": "RHP", "L": "LHP", "S": "SHP"}.get(h, hand)


def team_abbrev_to_id() -> dict[str, int]:
    """Static lookup: team abbreviation → MLB Stats API teamId."""
    return {
        "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112,
        "CWS": 145, "CIN": 113, "CLE": 114, "COL": 115, "DET": 116,
        "HOU": 117, "KC":  118, "LAA": 108, "LAD": 119, "MIA": 146,
        "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147, "OAK": 133,
        "PHI": 143, "PIT": 134, "SD":  135, "SEA": 136, "SF":  137,
        "STL": 138, "TB":  139, "TEX": 140, "TOR": 141, "WSH": 120,
    }


def score_to_grade(score: float, has_confirmed: bool, has_pitch_data: bool,
                    pitcher_bb_pct: Optional[float], batter_bb_pct: Optional[float],
                    weather_risk: bool) -> str:
    """Convert numeric suppression score to A+/A/B/C/D confidence grade."""
    if score >= 88 and has_confirmed and has_pitch_data \
            and (pitcher_bb_pct is None or pitcher_bb_pct <= 8.0) \
            and (batter_bb_pct  is None or batter_bb_pct  <= 10.0) \
            and not weather_risk:
        return "A+"
    if score >= 78 and has_confirmed and has_pitch_data \
            and (pitcher_bb_pct is None or pitcher_bb_pct <= 9.0) \
            and (batter_bb_pct  is None or batter_bb_pct  <= 11.0) \
            and not weather_risk:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def score_band_label(score: float) -> str:
    from config import SCORE_BANDS
    for threshold in sorted(SCORE_BANDS.keys(), reverse=True):
        if score >= threshold:
            return SCORE_BANDS[threshold]
    return "Avoid"


def reach_base_tier(prob: Optional[float]) -> str:
    """Convert a 0-1 probability into a verbal tier."""
    if prob is None:
        return "Unknown"
    from config import REACH_BASE_TIERS
    for threshold, label in sorted(REACH_BASE_TIERS.items()):
        if prob <= threshold:
            return label
    return "Very High"
