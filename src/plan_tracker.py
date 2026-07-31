"""Interactive race-plan tracking: completion state + plan loader.

Backs the /plan page. Stores per-user check-offs in SQLite (persistent disk on
Render), and loads the structured plan from config/race_plan_2026.json.
Mirrors the sqlite pattern in training_log.py.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.auth import get_db_connection

PLAN_PATH = Path(__file__).resolve().parents[1] / "config" / "race_plan_2026.json"
PLAN_PATHS = {
    "jonathan": PLAN_PATH,
    "robert": Path(__file__).resolve().parents[1] / "config" / "race_plan_2026_robert.json",
}


def init_plan_tables() -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at TIMESTAMP,
            notes TEXT,
            UNIQUE(user_id, item_id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    conn.commit()
    conn.close()


def load_plan(athlete: str = "jonathan") -> dict[str, Any]:
    """Load the structured plan JSON for an athlete (empty skeleton if missing)."""
    path = PLAN_PATHS.get(athlete, PLAN_PATH)
    if not path.exists():
        return {"meta": {}, "weeks": [], "templates": {}}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def get_completions(user_id: int) -> dict[str, dict[str, Any]]:
    """Return {item_id: {completed: bool, completed_at, notes}} for a user."""
    conn = get_db_connection()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT item_id, completed, completed_at, notes FROM plan_completions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    return {
        r["item_id"]: {
            "completed": bool(r["completed"]),
            "completed_at": r["completed_at"],
            "notes": r["notes"],
        }
        for r in rows
    }


def set_completion(user_id: int, item_id: str, completed: bool, notes: str | None = None) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO plan_completions (user_id, item_id, completed, completed_at, notes)
        VALUES (?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
        ON CONFLICT(user_id, item_id) DO UPDATE SET
            completed = excluded.completed,
            completed_at = CASE WHEN excluded.completed THEN CURRENT_TIMESTAMP ELSE NULL END,
            notes = COALESCE(excluded.notes, plan_completions.notes)
        """,
        (user_id, item_id, int(completed), int(completed), notes),
    )
    conn.commit()
    conn.close()


def all_item_ids(plan: dict[str, Any]) -> list[str]:
    """Every checkable session id across the plan (for progress math)."""
    ids: list[str] = []
    for week in plan.get("weeks", []):
        if str(week.get("id", "")).startswith("tmpl-"):
            continue  # templates are reference, not counted toward progress
        for day in week.get("days", []):
            for s in day.get("sessions", []):
                if s.get("id") and s.get("type") != "rest":
                    ids.append(s["id"])
    return ids


def progress_summary(plan: dict[str, Any], completions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ids = all_item_ids(plan)
    done = sum(1 for i in ids if completions.get(i, {}).get("completed"))
    total = len(ids)
    return {"done": done, "total": total, "pct": round(100 * done / total) if total else 0}


# ---------------- board weekly-view feeds ----------------
# The /board strip + tooltips + seven-weeks table read these instead of
# hardcoded template data, so plan rewrites show up on the board the moment
# the JSON is deployed (same source the /plan pages render from).

_BIG_RE = re.compile(r"\b(long|big vert|big climbing|dress rehearsal|recon)\b", re.I)


def _duration_hours(s: str | None) -> float:
    m = re.search(r"(\d+):(\d{2})", s or "")
    return int(m.group(1)) + int(m.group(2)) / 60 if m else 0.0


def plan_prescriptions(athlete: str) -> dict[str, dict[str, Any]]:
    """{date: {s, d, big?, race?, off?}} for the board strip/tooltips."""
    out: dict[str, dict[str, Any]] = {}
    for week in load_plan(athlete).get("weeks", []):
        if str(week.get("id", "")).startswith("tmpl-"):
            continue
        for day in week.get("days", []):
            date = day.get("date")
            if not date:
                continue
            headline = (day.get("headline") or "").strip()
            sessions = [s for s in day.get("sessions", []) if s.get("title")]
            titles = " + ".join(s["title"].strip() for s in sessions) or headline or "Rest"
            if len(titles) > 110:
                titles = titles[:107].rstrip() + "…"
            detail = ""
            for s in sessions:
                if s.get("targets"):
                    detail = s["targets"].strip()
                    break
            if not detail and sessions:
                detail = headline
            if len(detail) > 200:
                detail = detail[:197].rstrip() + "…"
            entry: dict[str, Any] = {"s": titles, "d": detail}
            if date == "2026-09-05" or "RACE" in headline.upper():
                entry["race"] = 1
            elif _BIG_RE.search(titles) or any(
                _duration_hours(s.get("duration")) >= 3.5 for s in sessions
            ):
                entry["big"] = 1
            if not sessions and "rest" in (headline or "rest").lower():
                entry["off"] = 1
            out[date] = entry
    return out


_WEEK_TAGS = (
    ("down", ("Down", "t-down")),
    ("re-entry", ("Re-entry", "t-down")),
    ("reentry", ("Re-entry", "t-down")),
    ("peak", ("Peak", "t-peak")),
    ("taper", ("Taper", "t-peak")),
    ("build", ("Build", "t-build")),
)


def _trim_focus(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for boundary in (". ", " · ", "; "):
        idx = cut.rfind(boundary)
        if idx > limit // 2:
            return cut[: idx + 1].rstrip() + "…"
    return cut.rstrip() + "…"


def plan_week_rows(start: str = "2026-07-19") -> list[dict[str, str]]:
    """Paired JA/RR week rows for the board's weeks table, from the plan JSONs."""

    def by_monday(athlete: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for week in load_plan(athlete).get("weeks", []):
            wid = str(week.get("id", ""))
            m = re.search(r"(\d{4}-\d{2}-\d{2})$", wid)
            if m and not wid.startswith("tmpl-"):
                out[m.group(1)] = week
        return out

    ja_weeks, rr_weeks = by_monday("jonathan"), by_monday("robert")
    rows = []
    for monday in sorted(ja_weeks):
        if monday < start:
            continue
        week = ja_weeks[monday]
        mon = datetime.strptime(monday, "%Y-%m-%d")
        sun = mon + timedelta(days=6)
        label = f"{mon.strftime('%b %-d')}–{sun.strftime('%-d') if sun.month == mon.month else sun.strftime('%b %-d')}"
        phase = (week.get("phase") or "").lower()
        tag, tag_class = "Build", "t-build"
        for key, (t, c) in _WEEK_TAGS:
            if key in phase:
                tag, tag_class = t, c
                break
        if "2026-09-05" >= monday and "2026-09-05" <= sun.strftime("%Y-%m-%d"):
            tag, tag_class = "RACE 🏁", "t-peak"
        rows.append(
            {
                "label": label,
                "tag": tag,
                "tag_class": tag_class,
                "ja": _trim_focus(week.get("focus", "")),
                "rr": _trim_focus(rr_weeks.get(monday, {}).get("focus", "")),
            }
        )
    return rows
