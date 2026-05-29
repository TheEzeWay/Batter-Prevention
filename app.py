"""
app.py – MLB Pitcher-Batter Suppression Dashboard
Run with:  streamlit run app.py
"""

import sys
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path so src.* imports work
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd

from config import (
    OUTPUTS_DIR, DEFAULT_TOP_PITCHERS, DEFAULT_TOP_TARGETS, DEFAULT_MIN_CONF,
)
from src.utils       import setup_logging
from src.cache       import cache_clear_all
from src.matchup_model  import run_pipeline, MatchupResult
from src.report_builder import (
    build_markdown_report, build_html_report,
    build_ranked_pitcher_csv, build_top_targets_csv,
    build_raw_json, save_all_outputs,
)

setup_logging("INFO")
logger = logging.getLogger(__name__)

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MLB Pitcher-Batter Suppression Dashboard",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main-header {
    font-size: 2.1rem; font-weight: 800; color: #1a1a2e;
    border-bottom: 3px solid #e94560; padding-bottom: 8px; margin-bottom: 4px;
  }
  .sub-header { font-size: 1rem; color: #555; margin-bottom: 20px; }
  .score-badge {
    display: inline-block; padding: 4px 12px; border-radius: 20px;
    font-weight: 700; font-size: 1.1rem;
    background: #1a1a2e; color: #fff;
  }
  .grade-a-plus { color: #00b300; font-weight: 800; font-size: 1.15rem; }
  .grade-a      { color: #33cc33; font-weight: 700; }
  .grade-b      { color: #0099ff; font-weight: 700; }
  .grade-c      { color: #ff9900; font-weight: 600; }
  .grade-d      { color: #cc0000; font-weight: 600; }
  .warning-box {
    background: #fff3cd; border-left: 4px solid #ffc107;
    padding: 10px 16px; border-radius: 4px; margin: 8px 0;
  }
  .risk-very-low  { color: #00b300; font-weight: 700; }
  .risk-low       { color: #66b300; font-weight: 700; }
  .risk-medium    { color: #cc8800; font-weight: 700; }
  .risk-high      { color: #cc0000; font-weight: 700; }
  .risk-very-high { color: #990000; font-weight: 800; }
  .stButton > button {
    background: #1a1a2e; color: #fff; border-radius: 8px;
    font-weight: 700; padding: 8px 20px;
  }
  .run-button > button {
    background: #e94560; color: #fff; font-size: 1.1rem;
    border-radius: 10px; padding: 12px 30px; font-weight: 800;
    width: 100%;
  }
</style>
""", unsafe_allow_html=True)


# ─── Sidebar settings ─────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://www.mlbstatic.com/team-logos/league-on-dark/1.svg", width=60)
    st.markdown("### ⚙️ Settings")

    use_confirmed_only = st.checkbox("Confirmed lineups only", value=False,
        help="If True, skip games where lineups are only projected.")
    allow_projected = st.checkbox("Allow projected lineups", value=True,
        help="Use RosterResource projected lineups when confirmed are unavailable.")
    min_conf = st.selectbox("Minimum confidence grade", ["A+", "A", "B", "C", "D"],
        index=3, help="Filter final report to matchups at or above this grade.")
    use_weather    = st.checkbox("Include weather adjustment",    value=True)
    use_park       = st.checkbox("Include park factor adjustment", value=True)
    use_pitch_matchup = st.checkbox("Include pitch-type matchup", value=True)
    use_zone_matchup  = st.checkbox("Include zone matchup",       value=True)
    top_pitchers_n = st.slider("Top pitchers to show",     min_value=1, max_value=15, value=5)
    top_targets_n  = st.slider("Top batter targets to show", min_value=1, max_value=9, value=4)

    st.markdown("---")
    st.markdown("**About**")
    st.caption("MLB Pitcher-Batter Suppression Dashboard v1.0\n"
               "Data: MLB Stats API · Baseball Savant · FanGraphs · Open-Meteo")

settings = {
    "use_confirmed_only": use_confirmed_only,
    "allow_projected":    allow_projected,
    "min_conf":           min_conf,
    "use_weather":        use_weather,
    "use_park_factor":    use_park,
    "use_pitch_matchup":  use_pitch_matchup,
    "use_zone_matchup":   use_zone_matchup,
    "top_pitchers":       top_pitchers_n,
    "top_targets":        top_targets_n,
}


# ─── Session state ────────────────────────────────────────────────────────────
for key in ("ranked", "overview", "md_report", "html_report",
            "pitcher_csv", "targets_csv", "raw_json", "last_run"):
    if key not in st.session_state:
        st.session_state[key] = None


# ─── Header ───────────────────────────────────────────────────────────────────
st.markdown('<div class="main-header">⚾ MLB Pitcher-Batter Suppression Dashboard</div>',
            unsafe_allow_html=True)
st.markdown('<div class="sub-header">One-click suppression report: which batters are least '
            'likely to reach base today?</div>', unsafe_allow_html=True)

# ─── Controls row ─────────────────────────────────────────────────────────────
col_date, col_run, col_refresh = st.columns([2, 3, 2])

with col_date:
    selected_date = st.date_input("Select date", value=date.today(),
                                   min_value=date(2024, 1, 1),
                                   max_value=date(2026, 12, 31))

with col_run:
    st.markdown('<div class="run-button">', unsafe_allow_html=True)
    run_clicked = st.button("▶  Run Today's MLB Suppression Report", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col_refresh:
    refresh_clicked = st.button("🔄  Refresh cached data")

if refresh_clicked:
    n = cache_clear_all()
    st.success(f"Cache cleared — {n} file(s) removed. Press Run to reload fresh data.")


# ─── Run pipeline ─────────────────────────────────────────────────────────────
if run_clicked:
    progress_msgs = [
        "Loading today's MLB slate...",
        "Fetching probable pitchers...",
        "Fetching lineups...",
        "Pulling pitcher stats...",
        "Pulling batter stats...",
        "Calculating pitcher suppression scores...",
        "Calculating batter reach-base risks...",
        "Ranking matchups...",
        "Generating final report...",
    ]

    progress_bar = st.progress(0)
    status_text  = st.empty()
    progress_log: list[str] = []

    msg_idx = [0]

    def _cb(msg: str):
        progress_log.append(msg)
        if msg_idx[0] < len(progress_msgs):
            pct = int((msg_idx[0] + 1) / len(progress_msgs) * 100)
            progress_bar.progress(pct)
            status_text.info(f"⏳ {msg}")
            msg_idx[0] += 1

    try:
        ranked, overview = run_pipeline(
            game_date   = selected_date,
            settings    = settings,
            progress_cb = _cb,
        )
    except Exception as exc:
        logger.exception("Pipeline error")
        st.error(f"Pipeline error: {exc}")
        ranked, overview = [], {}

    progress_bar.progress(100)
    status_text.success("✅ Done.")

    if overview.get("error"):
        st.warning(f"⚾ {overview['error']}")
    elif not ranked:
        st.warning("No matchups could be built for this date. Check the logs.")
    else:
        # Build reports
        md   = build_markdown_report(ranked, overview,
                                      settings, top_pitchers_n, top_targets_n)
        html = build_html_report(md)
        pcsv = build_ranked_pitcher_csv(ranked)
        tcsv = build_top_targets_csv(ranked)
        rjson= build_raw_json(overview, ranked)
        save_all_outputs(md, html, pcsv, tcsv, rjson)

        # Store in session
        st.session_state.ranked      = ranked
        st.session_state.overview    = overview
        st.session_state.md_report   = md
        st.session_state.html_report = html
        st.session_state.pitcher_csv = pcsv
        st.session_state.targets_csv = tcsv
        st.session_state.raw_json    = rjson
        st.session_state.last_run    = datetime.now().strftime("%Y-%m-%d %H:%M ET")

    st.rerun()


# ─── Display results ──────────────────────────────────────────────────────────
if st.session_state.ranked is not None:
    ranked: list[MatchupResult] = st.session_state.ranked
    overview = st.session_state.overview

    # Last-run info
    if st.session_state.last_run:
        st.caption(f"Last run: {st.session_state.last_run}")

    # ── Export buttons ────────────────────────────────────────────────────────
    st.markdown("### 📥 Export")
    ec1, ec2, ec3, ec4, ec5 = st.columns(5)
    with ec1:
        st.download_button("⬇ Markdown",  data=st.session_state.md_report,
                            file_name="mlb_suppression_report.md",
                            mime="text/markdown", use_container_width=True)
    with ec2:
        st.download_button("⬇ HTML",      data=st.session_state.html_report,
                            file_name="mlb_suppression_report.html",
                            mime="text/html",     use_container_width=True)
    with ec3:
        st.download_button("⬇ Pitcher CSV", data=st.session_state.pitcher_csv,
                            file_name="ranked_pitchers.csv",
                            mime="text/csv",      use_container_width=True)
    with ec4:
        st.download_button("⬇ Targets CSV", data=st.session_state.targets_csv,
                            file_name="top_batter_targets.csv",
                            mime="text/csv",      use_container_width=True)
    with ec5:
        st.download_button("⬇ Raw JSON",   data=st.session_state.raw_json,
                            file_name="raw_slate.json",
                            mime="application/json", use_container_width=True)

    st.markdown("---")

    # ── Tab layout ────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Slate Overview",
        "📊 Pitcher Rankings",
        "🔍 Breakdowns",
        "🎯 Pitch Matchups",
        "🏆 Final Report",
    ])

    # ── Tab 1: Slate Overview ─────────────────────────────────────────────────
    with tab1:
        st.subheader(f"Slate for {overview.get('date')}")
        oc1, oc2, oc3, oc4 = st.columns(4)
        oc1.metric("Total Games",        overview.get("total_games", 0))
        oc2.metric("Confirmed Lineups",  overview.get("confirmed_lineups", 0))
        oc3.metric("Projected Lineups",  overview.get("projected_lineups", 0))
        oc4.metric("Total Matchups",     overview.get("total_matchups", 0))

        wx_list = overview.get("weather_concerns", [])
        if wx_list:
            st.warning("⚠️ Weather Concerns: " + " | ".join(wx_list))
        else:
            st.success("✅ No significant weather concerns detected.")

        # Game list
        st.markdown("#### Games")
        games = overview.get("games", [])
        if games:
            def _fmt_time(utc_str):
                try:
                    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    return dt.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
                except Exception:
                    return utc_str[:16]

            rows = []
            for g in games:
                rows.append({
                    "Game Time":       _fmt_time(g.get("game_time_utc", "")),
                    "Away":            g.get("away_team", "?"),
                    "Home":            g.get("home_team", "?"),
                    "Venue":           g.get("venue", "?"),
                    "Away Pitcher":    g.get("away_pitcher") or "TBD",
                    "Home Pitcher":    g.get("home_pitcher") or "TBD",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Tab 2: Ranked Pitcher Table ───────────────────────────────────────────
    with tab2:
        st.subheader("Ranked Starting Pitcher Suppression Table")
        st.caption("Sorted by Suppression Score (highest = best suppression spot)")

        rows = []
        for i, m in enumerate(ranked, 1):
            best   = m.top_targets[0] if m.top_targets else None
            try:
                dt = datetime.fromisoformat(m.game_time_utc.replace("Z", "+00:00"))
                gt = dt.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
            except Exception:
                gt = "TBD"

            from src.utils import hand_label
            rows.append({
                "Rank":          i,
                "Game Time":     gt,
                "Pitcher":       m.pitcher_name,
                "Team":          m.pitcher_team,
                "Opponent":      m.opponent_team,
                "Hand":          hand_label(m.pitcher_hand),
                "Lineup":        m.lineup_status.capitalize(),
                "Best Target":   best.batter_name if best else "N/A",
                "Supp Score":    m.suppression_score,
                "Target Risk":   best.tier if best else "N/A",
                "Grade":         m.suppression_grade,
                "Weather":       m.weather.get("risk", "Unknown"),
            })

        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Supp Score": st.column_config.ProgressColumn(
                    "Suppression Score", min_value=0, max_value=100, format="%.1f",
                ),
            },
        )

    # ── Tab 3: Pitcher Breakdowns ──────────────────────────────────────────────
    with tab3:
        st.subheader(f"Top {min(top_pitchers_n, len(ranked))} Pitcher Breakdowns")
        for i, m in enumerate(ranked[:top_pitchers_n], 1):
            from src.utils import hand_label as hl, score_band_label
            try:
                dt = datetime.fromisoformat(m.game_time_utc.replace("Z", "+00:00"))
                gt = dt.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
            except Exception:
                gt = "TBD"

            with st.expander(
                f"#{i} {m.pitcher_name} vs {m.opponent_team} — "
                f"Score: {m.suppression_score}  |  Grade: {m.suppression_grade}",
                expanded=(i == 1),
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("Suppression Score", f"{m.suppression_score} / 100")
                c2.metric("Grade",             m.suppression_grade)
                c3.metric("Lineup Status",     m.lineup_status.capitalize())

                c4, c5, c6 = st.columns(3)
                c4.metric("Park Factor",   f"{m.park_factor:.2f}")
                wx = m.weather
                c5.metric("Temp",   f"{wx.get('temperature_f'):.0f}°F" if wx.get('temperature_f') else "N/A")
                c6.metric("Wind",   f"{wx.get('wind_speed_mph'):.0f} mph {wx.get('wind_direction','')}" if wx.get('wind_speed_mph') else "N/A")

                # Sub-scores chart
                st.markdown("**Score Components:**")
                sub_df = pd.DataFrame([
                    {"Component": k.replace("_", " ").title(), "Score": round(v, 1)}
                    for k, v in m.suppression_subs.items()
                ])
                st.bar_chart(sub_df.set_index("Component"), height=200)

                # Warnings
                for w in m.warnings:
                    st.warning(w)

                # Batter targets
                if m.top_targets:
                    st.markdown("**Top Batter Targets (Lowest Reach-Base Risk):**")
                    trows = []
                    for t in m.top_targets:
                        trows.append({
                            "Spot": t.lineup_spot,
                            "Batter": t.batter_name,
                            "Bats": t.bats or "?",
                            "Walk Risk": f"{t.walk_risk:.3f}",
                            "Hit Risk":  f"{t.hit_risk:.3f}",
                            "HBP Risk":  f"{t.hbp_risk:.4f}",
                            "Total Risk":f"{t.total_risk:.3f}",
                            "Tier": t.tier,
                            "Grade": t.grade,
                            "Trend": t.trend,
                        })
                    st.dataframe(pd.DataFrame(trows), use_container_width=True, hide_index=True)
                else:
                    st.info("No batter data available for this matchup.")

    # ── Tab 4: Pitch Matchups ──────────────────────────────────────────────────
    with tab4:
        st.subheader("Pitch Mix vs Batter Weakness")
        all_notes = []
        for m in ranked[:top_pitchers_n]:
            all_notes.extend(m.pitch_matchup_notes)

        if all_notes:
            notes_df = pd.DataFrame(all_notes)
            display_cols = [c for c in [
                "pitcher", "target_batter", "pitch_name", "pitch_type",
                "usage_pct", "pitcher_whiff_pct", "pitcher_xwoba", "edge_rating",
            ] if c in notes_df.columns]
            notes_df = notes_df[display_cols]
            notes_df.columns = [c.replace("_", " ").title() for c in display_cols]
            st.dataframe(notes_df, use_container_width=True, hide_index=True)
        else:
            st.info("Pitch arsenal data unavailable for today's slate. "
                    "This may occur early in the season or if Baseball Savant data is delayed.")

    # ── Tab 5: Final Report ────────────────────────────────────────────────────
    with tab5:
        st.subheader("🏆 Final Report: Top Batters Least Likely to Reach Base")

        # Collect and rank all unique batter targets
        all_targets = []
        for m in ranked:
            for t in m.batter_risks:
                if t.total_risk > 0:
                    all_targets.append((m, t))
        all_targets.sort(key=lambda x: x[1].total_risk)

        seen: set[str] = set()
        unique_targets = []
        for mt, bt in all_targets:
            if bt.batter_name not in seen:
                seen.add(bt.batter_name)
                unique_targets.append((mt, bt))

        for rank_idx, (m, t) in enumerate(unique_targets[:top_targets_n], 1):
            from src.utils import hand_label as hl
            try:
                dt = datetime.fromisoformat(m.game_time_utc.replace("Z", "+00:00"))
                gt = dt.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
            except Exception:
                gt = "TBD"

            tier_colors = {
                "Very Low": "#00b300", "Low": "#66b300",
                "Medium": "#cc8800",  "High": "#cc0000", "Very High": "#990000",
            }
            tier_color = tier_colors.get(t.tier, "#333")

            st.markdown(f"---")
            st.markdown(
                f"<h3>#{rank_idx} — "
                f"<span style='color:{tier_color}'>{t.batter_name}</span> "
                f"(vs {m.pitcher_name})</h3>",
                unsafe_allow_html=True,
            )

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Reach-Base Risk",  f"{t.total_risk:.3f}")
            r2.metric("Risk Tier",        t.tier)
            r3.metric("Confidence Grade", t.grade)
            r4.metric("Game Time",        gt)

            d1, d2, d3 = st.columns(3)
            d1.metric("Walk Risk", f"{t.walk_risk:.3f}")
            d2.metric("Hit Risk",  f"{t.hit_risk:.3f}")
            d3.metric("HBP Risk",  f"{t.hbp_risk:.4f}")

            info_rows = {
                "Pitcher":       f"{m.pitcher_name} ({hl(m.pitcher_hand)})",
                "Pitcher Team":  m.pitcher_team,
                "Opponent":      m.opponent_team,
                "Venue":         m.venue,
                "Lineup Spot":   str(t.lineup_spot),
                "Bats":          t.bats or "?",
                "Lineup Status": m.lineup_status.upper(),
                "Park Factor":   str(m.park_factor),
                "Recent Trend":  t.trend.title(),
            }
            st.table(pd.DataFrame(list(info_rows.items()), columns=["Field", "Value"]))

            # Pitch notes
            pitch_notes = [n for n in m.pitch_matchup_notes if n["target_batter"] == t.batter_name]
            if pitch_notes:
                st.markdown("**Pitch-Type Edge:**")
                pn_df = pd.DataFrame(pitch_notes)[[
                    "pitch_name", "pitch_type", "usage_pct", "pitcher_whiff_pct", "edge_rating"
                ]]
                pn_df.columns = ["Pitch", "Code", "Usage%", "Pitcher Whiff%", "Edge"]
                st.dataframe(pn_df, hide_index=True, use_container_width=True)

            # Notes / warnings
            if t.notes:
                with st.expander("Analysis notes"):
                    for note in t.notes:
                        st.markdown(f"- {note}")

            for w in m.warnings:
                st.warning(w)

        # Markdown preview
        with st.expander("📄 Full Markdown Report Preview"):
            st.markdown(st.session_state.md_report)

elif not run_clicked:
    # Landing state
    st.info(
        "👆 Select a date and press **Run Today's MLB Suppression Report** to generate the analysis.\n\n"
        "The pipeline will automatically fetch today's schedule, probable pitchers, lineups, "
        "Statcast data, and weather, then rank every pitcher-batter matchup."
    )
    with st.expander("ℹ️ How scores are calculated"):
        st.markdown("""
### Pitcher Suppression Score (0–100)

| Component | Weight | Description |
|---|---|---|
| Base-Prevention Skill | 25% | xFIP / FIP / ERA + xwOBA allowed |
| Walk Suppression | 15% | Low BB% = higher score |
| Strikeout / Whiff Profile | 15% | K%, whiff%, CSW%, K-BB% |
| Recent Form | 10% | Last 3–5 starts ERA/FIP |
| Opponent Weakness | 15% | Average OBP of opposing lineup |
| Pitch-Type Matchup | 10% | Batter whiff rate vs pitcher's best pitch |
| Zone Matchup | 5% | Chase rate overlap |
| Context (Park/Weather) | 5% | Park factor + weather risk |

### Batter Reach-Base Risk
Modeled as: P(walk) + P(hit) + P(HBP) via independent components blended from
season stats, recent form, pitcher suppression ability, and park factor.

### Confidence Grades
- **A+** = Confirmed lineup, elite stats, pitch/zone edge, no weather risk
- **A**  = Strong matchup, minor uncertainty
- **B**  = Good but some uncertainty
- **C**  = Usable
- **D**  = Avoid
        """)
