# ⚾ MLB Pitcher-Batter Suppression Dashboard

A one-click local web app that ranks MLB starting pitchers by their ability to
suppress opposing batters' reach-base probability, then outputs the **top 2
batters least likely to reach base** on today's slate — with full pitch-type
matchup analysis, Statcast metrics, weather context, and confidence grades.

---

## What It Does

1. Fetches every MLB game on the selected date
2. Identifies confirmed or projected starting pitchers
3. Fetches confirmed or projected lineups
4. Pulls pitcher stats: ERA, xERA, FIP, xFIP, SIERA, WHIP, K%, BB%, whiff rate,
   chase rate, barrel rate, OBP allowed, xwOBA, pitch arsenal
5. Pulls batter stats: OBP, xOBP, AVG, xBA, xwOBA, K%, BB%, chase/whiff rates,
   hard-hit rate, recent 7/15/30-day form, pitch-type splits
6. Computes a **Pitcher Suppression Score (0–100)** via 8 weighted components
7. Computes **Batter Reach-Base Risk** (walk + hit + HBP probability)
8. Ranks all pitcher-batter matchups
9. Outputs a clean final report with:
   - Ranked pitcher suppression table
   - Top 5 pitcher breakdowns
   - Pitch-mix vs batter-weakness table
   - **Final top 2 batter targets least likely to reach base**
   - Confidence grades (A+/A/B/C/D)

---

## Requirements

- Python 3.11 or later
- No API keys required (all data sources are public and free)

---

## Installation

```bash
git clone <repo>
cd mlb_suppression_app
pip install -r requirements.txt
```

---

## Running

```bash
streamlit run app.py
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Data Sources

| Source | URL | Key Needed |
|---|---|---|
| MLB Stats API | https://statsapi.mlb.com/api/v1 | No |
| Baseball Savant (Statcast) | https://baseballsavant.mlb.com | No |
| FanGraphs (via pybaseball) | https://fangraphs.com | No |
| Open-Meteo Weather | https://api.open-meteo.com | No |
| RosterResource Lineups | https://rosterresource.com | No |

---

## Scoring Method

### Pitcher Suppression Score (0–100)

| Component | Weight | How It's Calculated |
|---|---|---|
| Base-Prevention Skill | 25% | xFIP / FIP / ERA → inverted scale; blended with xwOBA + OBP-allowed |
| Walk Suppression | 15% | BB% → lower is better; 3% = 100, 15% = 0 |
| Strikeout / Whiff Profile | 15% | K%, whiff%, CSW%, K-BB% averaged |
| Recent Form | 10% | ERA/FIP of last starts; lower = higher score |
| Opponent Weakness | 15% | Average xOBP/OBP of opposing lineup (lineup-spot weighted) |
| Pitch-Type Matchup | 10% | Batter whiff/xwOBA vs pitcher's top 3 pitches |
| Zone Matchup | 5% | Pitcher chase rate × batter chase tendency overlap |
| Context (Park/Weather) | 5% | Park factor (Coors −20pts) + weather risk penalty |

Score interpretation:
- 90–100 = Elite suppression spot
- 80–89  = Strong suppression spot
- 70–79  = Playable but not elite
- 60–69  = Medium confidence
- < 60   = Avoid

### Batter Reach-Base Risk

```
P(reach) ≈ 1 − (1 − P_walk)(1 − P_hit)(1 − P_HBP)
```

- P(walk): 60% batter BB% + 40% pitcher BB%
- P(hit):  batter xBA × pitcher xwOBA resistance × strikeout adjustment
- P(HBP):  pitcher BB% as proxy for command (~0.9% base)
- Adjusted by: park factor, weather, recent form trend

Output tiers: Very Low / Low / Medium / High / Very High

### Confidence Grades

| Grade | Criteria |
|---|---|
| A+ | Score ≥ 88, confirmed lineup, pitch data present, pitcher BB% ≤ 8%, batter BB% ≤ 10%, no weather risk |
| A  | Score ≥ 78, confirmed lineup, pitch data, pitcher BB% ≤ 9%, no weather risk |
| B  | Score ≥ 65 |
| C  | Score ≥ 50 |
| D  | Score < 50 |

**Rules:** A/A+ grades are **never** given for projected lineups, missing pitch data,
poor pitcher command, high-walk batters, or weather risk.

---

## Interpreting the Final Report

- **#1 Batter Least Likely to Reach Base** = the batter in today's confirmed/projected
  lineups with the lowest estimated reach-base probability, factoring in all
  pitcher and batter metrics above.
- **Total Reach-Base Risk** ≈ probability the batter reaches base in a given PA.
  Very Low (< 0.20) is ideal; Low (< 0.28) is strong.
- **Grade** reflects data completeness and matchup quality, not just score.
  Always prefer A/A+ grades; be cautious with B/C.
- **Lineup Changed Warning**: If lineups were projected, rerun after confirmed
  lineups post (usually 3–4 hours before first pitch).

---

## Project Structure

```
mlb_suppression_app/
├── app.py                  # Streamlit UI + pipeline runner
├── config.py               # All constants, weights, park factors
├── requirements.txt
├── .env.example
├── README.md
├── src/
│   ├── cache.py            # File-based JSON cache with TTL
│   ├── utils.py            # HTTP helpers, type coercion, formatters
│   ├── data_sources.py     # Data source registry
│   ├── mlb_schedule.py     # MLB Stats API schedule fetch
│   ├── lineups.py          # Confirmed + projected lineup fetch
│   ├── player_ids.py       # MLBAM player ID resolution
│   ├── statcast_data.py    # Pitcher/batter Statcast + pybaseball
│   ├── pitcher_model.py    # PitcherProfile dataclass builder
│   ├── batter_model.py     # BatterProfile dataclass builder
│   ├── weather.py          # Open-Meteo weather fetch
│   ├── scoring.py          # Suppression score + reach-base risk
│   ├── matchup_model.py    # Full pipeline orchestrator
│   └── report_builder.py  # Markdown / HTML / CSV / JSON export
├── outputs/
│   ├── today_report.md
│   ├── today_report.html
│   ├── ranked_pitchers.csv
│   ├── top_batter_targets.csv
│   └── raw_slate.json
└── cache/                  # Auto-managed cache files
```

---

## Known Limitations

1. **FanGraphs via pybaseball** may time out during peak hours; Statcast CSV is
   used as fallback automatically.
2. **Confirmed lineups** are only available ~3–4 hours before first pitch on MLB
   Stats API. Before that, projected lineups from RosterResource are used.
3. **Pitch-type batter splits** require enough PA volume; early-season data may
   be thin and confidence grades will reflect this.
4. **Reached-on-error** is excluded (data unavailable on public endpoints).
5. **Catcher interference** is excluded.
6. **Umpire tendencies** are not modeled (no free public endpoint).
7. **Betting implied totals** are not included; The Odds API key can be added
   via `.env` for future enhancement.
8. Weather is from Open-Meteo (free) and may differ slightly from ballpark
   conditions for dome stadiums — these are flagged automatically.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `ModuleNotFoundError: pybaseball` | `pip install pybaseball` |
| `ModuleNotFoundError: zoneinfo` | Upgrade to Python 3.11+ |
| Blank pitcher stats | Statcast leaderboard may be delayed; press Refresh |
| "No MLB games found" | API may be slow; try Refresh or check date |
| Slow first run | pybaseball downloads FanGraphs data; subsequent runs use cache |
| Cache stale data | Press "Refresh cached data" button in the UI |

---

## Next Improvements

- [ ] Add The Odds API integration for implied totals
- [ ] Add head-to-head pitcher vs batter career splits
- [ ] Add umpire K-rate tendency (via Statcast umpire data)
- [ ] Add bullpen depth / pitcher pitch-count model
- [ ] Add injury feed (MLB Stats API transaction endpoint)
- [ ] Add daily email/Slack report delivery
- [ ] Add historical backtesting dashboard
- [ ] Add DFS correlation (FanDuel/DraftKings salary integration)
