"""
config.py – Central configuration for MLB Pitcher-Batter Suppression Dashboard.
All tuneable constants live here so nothing is hard-coded elsewhere.
"""

from pathlib import Path

# ── Directory layout ──────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.resolve()
CACHE_DIR   = BASE_DIR / "cache"
OUTPUTS_DIR = BASE_DIR / "outputs"
SRC_DIR     = BASE_DIR / "src"

CACHE_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# ── MLB Stats API ─────────────────────────────────────────────────────────────
MLB_API_BASE      = "https://statsapi.mlb.com/api/v1"
MLB_API_BASE_V11  = "https://statsapi.mlb.com/api/v1.1"
MLB_REQUEST_TIMEOUT = 15          # seconds
MLB_RATE_LIMIT_PAUSE = 0.4        # seconds between heavy loops

# ── Baseball Savant / Statcast ────────────────────────────────────────────────
SAVANT_BASE      = "https://baseballsavant.mlb.com"
SAVANT_SEARCH    = f"{SAVANT_BASE}/statcast_search/csv"
SAVANT_LEADERBOARD = f"{SAVANT_BASE}/leaderboard"

# ── pybaseball cache ──────────────────────────────────────────────────────────
PYBASEBALL_CACHE = True           # enable pybaseball's built-in disk cache

# ── Open-Meteo (free weather, no key needed) ──────────────────────────────────
WEATHER_API_BASE = "https://api.open-meteo.com/v1/forecast"
GEOCODE_API_BASE = "https://geocoding-api.open-meteo.com/v1/search"

# ── RosterResource lineup scraper ─────────────────────────────────────────────
ROSTERRESOURCE_URL = "https://www.rosterresource.com/mlb-starting-lineups"

# ── Cache TTL (seconds) ───────────────────────────────────────────────────────
CACHE_TTL = {
    "schedule":       3600 * 4,   # 4 hours
    "probable_pitchers": 3600 * 2,
    "lineups":        3600 * 1,   # 1 hour – lineups change late
    "player_ids":     3600 * 24,
    "pitcher_stats":  3600 * 6,
    "batter_stats":   3600 * 6,
    "statcast":       3600 * 12,
    "weather":        3600 * 1,
    "park_factors":   3600 * 24,
}

# ── Scoring weights (must sum to 1.0) ─────────────────────────────────────────
SUPPRESSION_WEIGHTS = {
    "base_prevention":     0.25,
    "walk_suppression":    0.15,
    "strikeout_whiff":     0.15,
    "recent_form":         0.10,
    "opponent_weakness":   0.15,
    "pitch_type_matchup":  0.10,
    "zone_matchup":        0.05,
    "context":             0.05,
}

# ── Score interpretation bands ────────────────────────────────────────────────
SCORE_BANDS = {
    90: "Elite suppression spot",
    80: "Strong suppression spot",
    70: "Playable but not elite",
    60: "Medium confidence",
     0: "Avoid",
}

# ── Confidence grade thresholds ───────────────────────────────────────────────
CONFIDENCE_RULES = {
    "A+": {
        "min_score":           88,
        "confirmed_lineup":    True,
        "has_pitch_type_data": True,
        "max_pitcher_bb_pct":  8.0,  # %
        "max_batter_bb_pct":   10.0,
        "no_weather_risk":     True,
    },
    "A": {
        "min_score":           78,
        "confirmed_lineup":    True,
        "has_pitch_type_data": True,
        "max_pitcher_bb_pct":  9.0,
        "max_batter_bb_pct":   11.0,
        "no_weather_risk":     True,
    },
    "B": {"min_score": 65},
    "C": {"min_score": 50},
    "D": {"min_score":  0},
}

# ── Reach-base risk tiers ─────────────────────────────────────────────────────
REACH_BASE_TIERS = {
    0.20: "Very Low",
    0.28: "Low",
    0.34: "Medium",
    0.40: "High",
    1.00: "Very High",
}

# ── Park factors (neutral = 1.0). Source: FanGraphs 2025 multi-year park factors
# These are rough run-environment scalars; refined data pulled at runtime if available.
PARK_FACTORS: dict[str, float] = {
    "Coors Field":                   1.23,
    "Great American Ball Park":      1.12,
    "Fenway Park":                   1.09,
    "Globe Life Field":              1.05,
    "Yankee Stadium":                1.04,
    "Camden Yards":                  1.03,
    "Wrigley Field":                 1.02,
    "Chase Field":                   1.01,
    "Guaranteed Rate Field":         1.01,
    "Dodger Stadium":                0.98,
    "loanDepot park":                0.97,
    "Petco Park":                    0.94,
    "Oracle Park":                   0.93,
    "T-Mobile Park":                 0.94,
    "Tropicana Field":               0.96,
    "American Family Field":         1.02,
    "Busch Stadium":                 0.96,
    "PNC Park":                      0.95,
    "Nationals Park":                1.00,
    "Citi Field":                    0.97,
    "Progressive Field":             1.00,
    "Target Field":                  0.98,
    "Kauffman Stadium":              0.97,
    "Minute Maid Park":              1.00,
    "Angel Stadium":                 0.97,
    "Oakland Coliseum":              0.95,
    "Rogers Centre":                 1.03,
    "Truist Park":                   1.01,
    "Citizens Bank Park":            1.07,
    "Sahlen Field":                  1.00,  # fallback
}

# ── Top lineup spots weight (lower spot = more PA exposure) ───────────────────
LINEUP_SPOT_WEIGHT = {1: 1.10, 2: 1.08, 3: 1.06, 4: 1.04, 5: 1.02,
                      6: 1.00, 7: 0.98, 8: 0.96, 9: 0.94}

# ── Display defaults ──────────────────────────────────────────────────────────
DEFAULT_TOP_PITCHERS  = 5
DEFAULT_TOP_TARGETS   = 2
DEFAULT_MIN_CONF      = "C"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
