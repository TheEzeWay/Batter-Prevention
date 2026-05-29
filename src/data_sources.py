"""
data_sources.py – Thin wrapper that exposes all external data sources
in one place. Used by app.py and report_builder.py for diagnostics.
"""

DATA_SOURCES = {
    "MLB Stats API": {
        "url":     "https://statsapi.mlb.com/api/v1",
        "key":     False,
        "desc":    "Schedule, probable pitchers, game lineups, player IDs",
        "free":    True,
    },
    "Baseball Savant (Statcast)": {
        "url":     "https://baseballsavant.mlb.com",
        "key":     False,
        "desc":    "Pitcher/batter Statcast leaderboards, pitch arsenal splits",
        "free":    True,
    },
    "pybaseball": {
        "url":     "https://github.com/jldbc/pybaseball",
        "key":     False,
        "desc":    "FanGraphs batting/pitching stats; player ID cross-reference",
        "free":    True,
    },
    "Open-Meteo": {
        "url":     "https://api.open-meteo.com",
        "key":     False,
        "desc":    "Free weather forecasts – temperature, wind, precipitation",
        "free":    True,
    },
    "RosterResource": {
        "url":     "https://www.rosterresource.com/mlb-starting-lineups",
        "key":     False,
        "desc":    "Projected starting lineups (HTML parse, best-effort)",
        "free":    True,
    },
}


def print_data_sources() -> str:
    lines = ["## Data Sources\n"]
    for name, info in DATA_SOURCES.items():
        key_str = "API key required" if info["key"] else "No API key needed"
        lines.append(f"**{name}** ({key_str})")
        lines.append(f"  - URL: {info['url']}")
        lines.append(f"  - {info['desc']}\n")
    return "\n".join(lines)
