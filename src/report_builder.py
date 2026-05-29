"""
report_builder.py – Generate Markdown, HTML, and CSV reports from MatchupResults.
"""

import csv
import io
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from config import OUTPUTS_DIR
from src.matchup_model import MatchupResult, BatterRiskResult
from src.utils import hand_label, fmt_stat, fmt_pct

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _game_time_local(utc_str: str) -> str:
    """Convert ISO UTC string to US Eastern display string."""
    if not utc_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        # Convert to Eastern
        from zoneinfo import ZoneInfo
        et   = dt.astimezone(ZoneInfo("America/New_York"))
        ampm = et.strftime("%-I:%M %p ET")
        return ampm
    except Exception:
        return utc_str[:16]


def _tier_emoji(tier: str) -> str:
    return {"Very Low": "🟢", "Low": "🟡", "Medium": "🟠",
            "High": "🔴", "Very High": "🔴", "Unknown": "⚪"}.get(tier, "⚪")


def _grade_emoji(grade: str) -> str:
    return {"A+": "🏆", "A": "⭐", "B": "✅", "C": "⚠️", "D": "❌"}.get(grade, "")


# ── Markdown Report ───────────────────────────────────────────────────────────

def build_markdown_report(
    ranked:   list[MatchupResult],
    overview: dict,
    settings: Optional[dict] = None,
    top_n_pitchers: int = 5,
    top_n_targets:  int = 2,
) -> str:
    s    = settings or {}
    date_str = overview.get("date", str(date.today()))
    lines: list[str] = []

    lines.append(f"# MLB Pitcher-Batter Suppression Report")
    lines.append(f"**Date:** {date_str}  |  **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    lines.append("")
    lines.append("> Reached-on-error excluded due to unavailable data.")
    lines.append("")

    # ── Slate Overview ────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## 1. Slate Overview")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Date | {date_str} |")
    lines.append(f"| Total Games | {overview.get('total_games', 'N/A')} |")
    lines.append(f"| Confirmed Lineups | {overview.get('confirmed_lineups', 0)} |")
    lines.append(f"| Projected Lineups | {overview.get('projected_lineups', 0)} |")
    lines.append(f"| Unavailable Lineups | {overview.get('unavailable_lineups', 0)} |")
    wx = overview.get("weather_concerns", [])
    lines.append(f"| Weather Concerns | {', '.join(wx) if wx else 'None'} |")
    lines.append("")

    if not ranked:
        lines.append("**No matchup data available for this date.**")
        return "\n".join(lines)

    # ── Ranked Pitcher Table ──────────────────────────────────────────────────
    lines.append("---")
    lines.append("## 2. Ranked Starting Pitcher Suppression Table")
    lines.append("")
    lines.append("| Rank | Game Time | Pitcher | Team | Opponent | Hand | Lineup | Best Target | Supp Score | Target Risk | Grade |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    for i, m in enumerate(ranked, start=1):
        best   = m.top_targets[0] if m.top_targets else None
        t_name = best.batter_name if best else "N/A"
        t_risk = best.tier        if best else "N/A"
        t_emoji= _tier_emoji(t_risk) if best else ""
        lines.append(
            f"| {i} | {_game_time_local(m.game_time_utc)} | **{m.pitcher_name}** | "
            f"{m.pitcher_team} | {m.opponent_team} | {hand_label(m.pitcher_hand)} | "
            f"{m.lineup_status.capitalize()} | {t_name} | **{m.suppression_score}** | "
            f"{t_emoji} {t_risk} | {_grade_emoji(m.suppression_grade)} {m.suppression_grade} |"
        )

    lines.append("")

    # ── Top N Pitcher Breakdowns ──────────────────────────────────────────────
    lines.append("---")
    lines.append(f"## 3. Top {min(top_n_pitchers, len(ranked))} Pitcher Suppression Breakdowns")

    for i, m in enumerate(ranked[:top_n_pitchers], start=1):
        lines.append("")
        lines.append(f"### #{i} — {m.pitcher_name} ({hand_label(m.pitcher_hand)}) vs {m.opponent_team}")
        lines.append("")
        lines.append(f"| Field | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Pitcher | {m.pitcher_name} |")
        lines.append(f"| Opponent | {m.opponent_team} |")
        lines.append(f"| Game Time | {_game_time_local(m.game_time_utc)} |")
        lines.append(f"| Venue | {m.venue} (Park Factor: {m.park_factor:.2f}) |")
        lines.append(f"| Lineup Status | **{m.lineup_status.upper()}** |")
        lines.append(f"| Suppression Score | **{m.suppression_score} / 100** — {m.suppression_label} |")
        lines.append(f"| Confidence Grade | {_grade_emoji(m.suppression_grade)} **{m.suppression_grade}** |")
        lines.append("")

        # Sub-scores
        lines.append("**Score Breakdown:**")
        lines.append("")
        lines.append("| Component | Score |")
        lines.append("|---|---|")
        for comp, val in m.suppression_subs.items():
            lines.append(f"| {comp.replace('_', ' ').title()} | {val:.1f} |")
        lines.append("")

        # Top weak targets
        if m.top_targets:
            lines.append("**Weakest Opposing Batters (Top Targets):**")
            lines.append("")
            lines.append("| # | Batter | Spot | Bats | OBP Risk | Walk | Hit | HBP | Tier | Grade | Trend |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
            for j, t in enumerate(m.top_targets, 1):
                lines.append(
                    f"| {j} | {t.batter_name} | {t.lineup_spot} | {t.bats or '?'} | "
                    f"{t.total_risk:.3f} | {t.walk_risk:.3f} | {t.hit_risk:.3f} | "
                    f"{t.hbp_risk:.4f} | {_tier_emoji(t.tier)} {t.tier} | "
                    f"{_grade_emoji(t.grade)} {t.grade} | {t.trend} |"
                )
            lines.append("")

        # Weather
        wx = m.weather
        if wx and wx.get("temperature_f") is not None:
            lines.append(f"**Weather @ {m.venue}:** "
                         f"{wx.get('temperature_f'):.0f}°F, "
                         f"Wind {wx.get('wind_speed_mph'):.0f} mph {wx.get('wind_direction','')}, "
                         f"Precip {wx.get('precip_prob_pct'):.0f}%, "
                         f"Risk: **{wx.get('risk')}**")
            lines.append("")

        # Warnings
        for w in m.warnings:
            lines.append(f"> {w}")
        if m.warnings:
            lines.append("")

    # ── Pitch Mix vs Batter Weakness Table ────────────────────────────────────
    all_notes = []
    for m in ranked[:top_n_pitchers]:
        all_notes.extend(m.pitch_matchup_notes)

    if all_notes:
        lines.append("---")
        lines.append("## 4. Pitch Mix vs Batter Weakness")
        lines.append("")
        lines.append("| Pitcher | Target Batter | Pitch | Usage% | Pitcher Whiff% | Edge |")
        lines.append("|---|---|---|---|---|---|")
        for n in all_notes:
            lines.append(
                f"| {n['pitcher']} | {n['target_batter']} | "
                f"{n['pitch_name']} ({n['pitch_type']}) | "
                f"{fmt_pct(n['usage_pct'])} | {fmt_pct(n['pitcher_whiff_pct'])} | "
                f"**{n['edge_rating']}** |"
            )
        lines.append("")

    # ── Final Report: Top 2 Batters ────────────────────────────────────────────
    lines.append("---")
    lines.append("## 5. Final Report: Top Batters Least Likely to Reach Base")
    lines.append("")

    # Collect all batter targets across all matchups, sort by lowest total_risk
    all_targets: list[tuple[MatchupResult, BatterRiskResult]] = []
    for m in ranked:
        for t in m.batter_risks:
            if t.total_risk > 0:
                all_targets.append((m, t))

    # Sort by total risk (lowest = best suppression target)
    all_targets.sort(key=lambda x: x[1].total_risk)

    # Deduplicate by batter name
    seen_batters: set[str] = set()
    unique_targets = []
    for mt, bt in all_targets:
        if bt.batter_name not in seen_batters:
            seen_batters.add(bt.batter_name)
            unique_targets.append((mt, bt))

    for rank_idx, (m, t) in enumerate(unique_targets[:top_n_targets], start=1):
        lines.append(f"### #{rank_idx} Batter Least Likely to Reach Base")
        lines.append("")
        lines.append(f"| Field | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Pitcher | {m.pitcher_name} ({hand_label(m.pitcher_hand)}) |")
        lines.append(f"| Pitcher Team | {m.pitcher_team} |")
        lines.append(f"| Opponent | {m.opponent_team} |")
        lines.append(f"| Game Time | {_game_time_local(m.game_time_utc)} |")
        lines.append(f"| Target Batter | **{t.batter_name}** |")
        lines.append(f"| Batter Team | {m.opponent_team} |")
        lines.append(f"| Lineup Spot | {t.lineup_spot} |")
        lines.append(f"| Lineup Status | {m.lineup_status.upper()} |")
        lines.append(f"| Estimated Reach-Base Risk | {_tier_emoji(t.tier)} **{t.tier}** ({t.total_risk:.3f}) |")
        lines.append(f"| Confidence Grade | {_grade_emoji(t.grade)} **{t.grade}** |")
        lines.append("")
        lines.append(f"| Risk Component | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Walk Risk | {t.walk_risk:.3f} |")
        lines.append(f"| Hit Risk | {t.hit_risk:.3f} |")
        lines.append(f"| HBP Risk | {t.hbp_risk:.4f} |")
        lines.append(f"| **Total Reach-Base Risk** | **{t.total_risk:.3f}** |")
        lines.append("")

        # Narrative
        lines.append("**Why this is the best target:**")
        lines.append("")
        if t.notes:
            for note in t.notes:
                lines.append(f"- {note}")
        else:
            lines.append(f"- Low season OBP profile combined with pitcher command advantage.")
        lines.append("")

        # Pitch edge
        pitch_notes = [n for n in m.pitch_matchup_notes if n["target_batter"] == t.batter_name]
        if pitch_notes:
            pn = pitch_notes[0]
            lines.append(f"**Pitch-type edge:** Pitcher's {pn['pitch_name']} ({pn['pitch_type']}) "
                         f"used {fmt_pct(pn['usage_pct'])} of the time, "
                         f"generating {fmt_pct(pn['pitcher_whiff_pct'])} whiff rate. "
                         f"Edge rating: **{pn['edge_rating']}**")
        else:
            lines.append("**Pitch-type edge:** Pitch-type split data unavailable.")
        lines.append("")

        lines.append(f"**Recent form edge:** {t.trend.title()}")
        lines.append("")

        # Platoon edge
        hand_txt = hand_label(m.pitcher_hand)
        bats_txt = t.bats or "Unknown"
        platoon  = "Advantage" if (m.pitcher_hand == "R" and t.bats == "R") or \
                                   (m.pitcher_hand == "L" and t.bats == "L") else "Neutral/Disadvantage"
        lines.append(f"**Platoon edge:** {hand_txt} pitcher vs {bats_txt}-handed batter — {platoon}")
        lines.append("")

        lines.append(f"**Main risk:** {'Lineup not confirmed. ' if m.lineup_status != 'confirmed' else ''}"
                     f"{'Weather concern. ' if m.weather.get('risk_flag') else ''}"
                     f"{'Missing pitch-type data. ' if not m.pitch_matchup_notes else ''}")
        lines.append("")

        # Warnings
        for w in m.warnings:
            lines.append(f"> {w}")
        if m.warnings:
            lines.append("")

    lines.append("---")
    lines.append("*Report generated by MLB Pitcher-Batter Suppression Dashboard. "
                 "Reached-on-error excluded due to unavailable data. "
                 "All stats from public MLB Stats API, Baseball Savant, and FanGraphs via pybaseball.*")

    return "\n".join(lines)


# ── HTML Export ───────────────────────────────────────────────────────────────

def build_html_report(markdown_text: str) -> str:
    """Convert markdown to simple HTML using markdown2 if available."""
    try:
        import markdown2
        html_body = markdown2.markdown(markdown_text, extras=["tables", "fenced-code-blocks"])
    except ImportError:
        # Minimal fallback
        html_body = f"<pre>{markdown_text}</pre>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MLB Suppression Report</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1100px; margin: 40px auto; padding: 0 20px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #1a1a2e; color: #fff; }}
  tr:nth-child(even) {{ background: #f4f4f8; }}
  h1 {{ color: #1a1a2e; }} h2 {{ color: #16213e; border-bottom: 2px solid #e94560; }}
  h3 {{ color: #0f3460; }}
  blockquote {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 8px 16px; }}
  code {{ background: #f4f4f4; padding: 2px 4px; border-radius: 3px; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""


# ── CSV Exports ───────────────────────────────────────────────────────────────

def build_ranked_pitcher_csv(ranked: list[MatchupResult]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "Rank", "Pitcher", "Team", "Opponent", "Hand", "Game Time",
        "Venue", "Park Factor", "Suppression Score", "Grade", "Label",
        "Lineup Status", "Best Target", "Target Risk Tier", "Target Total Risk",
        "Weather Risk",
    ])
    for i, m in enumerate(ranked, 1):
        best   = m.top_targets[0] if m.top_targets else None
        writer.writerow([
            i, m.pitcher_name, m.pitcher_team, m.opponent_team,
            hand_label(m.pitcher_hand),
            _game_time_local(m.game_time_utc),
            m.venue, m.park_factor,
            m.suppression_score, m.suppression_grade, m.suppression_label,
            m.lineup_status,
            best.batter_name if best else "N/A",
            best.tier        if best else "N/A",
            f"{best.total_risk:.3f}" if best else "N/A",
            m.weather.get("risk", "Unknown"),
        ])
    return out.getvalue()


def build_top_targets_csv(ranked: list[MatchupResult]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "Pitcher", "Pitcher Team", "Pitcher Hand",
        "Opponent Team", "Game Time", "Venue",
        "Target Batter", "Lineup Spot", "Bats",
        "Lineup Status", "Walk Risk", "Hit Risk", "HBP Risk",
        "Total Risk", "Risk Tier", "Grade", "Trend",
    ])
    for m in ranked:
        for t in m.top_targets:
            writer.writerow([
                m.pitcher_name, m.pitcher_team, hand_label(m.pitcher_hand),
                m.opponent_team, _game_time_local(m.game_time_utc), m.venue,
                t.batter_name, t.lineup_spot, t.bats or "?",
                m.lineup_status,
                f"{t.walk_risk:.3f}", f"{t.hit_risk:.3f}",
                f"{t.hbp_risk:.4f}", f"{t.total_risk:.3f}",
                t.tier, t.grade, t.trend,
            ])
    return out.getvalue()


# ── JSON Export ───────────────────────────────────────────────────────────────

def build_raw_json(overview: dict, ranked: list[MatchupResult]) -> str:
    def _matchup_dict(m: MatchupResult) -> dict:
        return {
            "pitcher_name":      m.pitcher_name,
            "pitcher_team":      m.pitcher_team,
            "pitcher_hand":      m.pitcher_hand,
            "opponent_team":     m.opponent_team,
            "game_time_utc":     m.game_time_utc,
            "venue":             m.venue,
            "park_factor":       m.park_factor,
            "suppression_score": m.suppression_score,
            "suppression_grade": m.suppression_grade,
            "lineup_status":     m.lineup_status,
            "weather_risk":      m.weather.get("risk"),
            "top_targets": [
                {
                    "batter_name":  t.batter_name,
                    "lineup_spot":  t.lineup_spot,
                    "bats":         t.bats,
                    "walk_risk":    t.walk_risk,
                    "hit_risk":     t.hit_risk,
                    "hbp_risk":     t.hbp_risk,
                    "total_risk":   t.total_risk,
                    "tier":         t.tier,
                    "grade":        t.grade,
                    "trend":        t.trend,
                }
                for t in m.top_targets
            ],
            "warnings": m.warnings,
        }

    payload = {
        "overview":  overview,
        "matchups":  [_matchup_dict(m) for m in ranked],
    }
    return json.dumps(payload, indent=2, default=str)


# ── Save all outputs ──────────────────────────────────────────────────────────

def save_all_outputs(markdown: str, html: str,
                      pitcher_csv: str, targets_csv: str,
                      raw_json: str) -> None:
    """Write all output files to /outputs/."""
    (OUTPUTS_DIR / "today_report.md").write_text(markdown,     encoding="utf-8")
    (OUTPUTS_DIR / "today_report.html").write_text(html,       encoding="utf-8")
    (OUTPUTS_DIR / "ranked_pitchers.csv").write_text(pitcher_csv, encoding="utf-8")
    (OUTPUTS_DIR / "top_batter_targets.csv").write_text(targets_csv, encoding="utf-8")
    (OUTPUTS_DIR / "raw_slate.json").write_text(raw_json,      encoding="utf-8")
    logger.info("All outputs saved to %s", OUTPUTS_DIR)
