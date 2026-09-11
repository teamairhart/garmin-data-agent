"""Strength & Conditioning plan helpers (config/strength_plan_2027.json)."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PLAN_PATH = Path(__file__).resolve().parents[1] / "config" / "strength_plan_2027.json"


def load_strength_plan(path: Path | None = None) -> dict[str, Any]:
    p = path or PLAN_PATH
    if not p.exists():
        return {"meta": {}, "goals": [], "phases": [], "ladder": [], "weekly_templates": {}, "rules": [], "hotel": []}
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def current_phase(plan: dict[str, Any], today: date) -> dict[str, Any] | None:
    phases = plan.get("phases", [])
    iso = today.isoformat()
    for ph in phases:
        if ph["start"] <= iso <= ph["end"]:
            return ph
    if phases and iso < phases[0]["start"]:
        return phases[0]
    return phases[-1] if phases else None


def phase_progress(phase: dict[str, Any] | None, today: date) -> dict[str, int]:
    if not phase:
        return {"day": 0, "total": 0, "pct": 0}
    start, end = date.fromisoformat(phase["start"]), date.fromisoformat(phase["end"])
    total = (end - start).days + 1
    day = min(max((today - start).days + 1, 0), total)
    return {"day": day, "total": total, "pct": int(round(100 * day / total)) if total else 0}


def days_to_race(plan: dict[str, Any], today: date) -> int | None:
    rd = plan.get("meta", {}).get("race_date")
    return (date.fromisoformat(rd) - today).days if rd else None


def ladder_status(plan: dict[str, Any], best_e1rm: float | None, today: date) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Each rung gets status met / due (date passed, not met) / upcoming; also returns the next unmet rung."""
    rows: list[dict[str, Any]] = []
    next_rung: dict[str, Any] | None = None
    iso = today.isoformat()
    for r in plan.get("ladder", []):
        row = dict(r)
        met = best_e1rm is not None and best_e1rm >= r["e1rm"]
        row["status"] = "met" if met else ("due" if r["date"] <= iso else "upcoming")
        row["label"] = date.fromisoformat(r["date"]).strftime("%b %-d, %Y")
        if not met and next_rung is None:
            next_rung = row
        rows.append(row)
    return rows, next_rung


_KEYWORDS = ("upper", "lower", "full", "core")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _keyword(title: str) -> str | None:
    t = _norm(title)
    for k in _KEYWORDS:
        if k in t:
            return k
    if "big 3" in t or "big three" in t:
        return "core"
    return None


def week_view(plan: dict[str, Any], phase: dict[str, Any] | None, sessions_this_week: list[dict[str, Any]]) -> dict[str, Any]:
    """The phase's weekly template with logged sessions matched onto it.
    A logged strength session ticks the first unticked template row with the same name, else the first
    unticked strength row sharing its keyword (upper/lower/full) — so 'Freestyle Upper' or 'Hotel Upper'
    still count. Core-type logged sessions are counted against the Big 3 row."""
    rows = [dict(r) for r in plan.get("weekly_templates", {}).get(phase["id"] if phase else "", [])]
    for r in rows:
        r["done"] = False
        r["matched"] = None
    strength_rows = [r for r in rows if r.get("type") == "strength"]
    logged = sorted(sessions_this_week, key=lambda s: s["session_date"])
    core_logged = 0
    for s in logged:
        if s.get("session_type") == "core" or (_keyword(s["title"]) == "core"):
            core_logged += 1
            continue
        target = next((r for r in strength_rows if not r["done"] and _norm(r["session"]) == _norm(s["title"])), None)
        if target is None:
            kw = _keyword(s["title"])
            target = next((r for r in strength_rows if not r["done"] and kw and _keyword(r["session"]) == kw), None)
        if target is None:
            target = next((r for r in strength_rows if not r["done"]), None)
        if target is not None:
            target["done"] = True
            target["matched"] = f"{s['title']} · {s['label']}"
    for r in rows:
        if r.get("type") == "core":
            r["core_logged"] = core_logged
    return {"rows": rows,
            "planned_strength": len(strength_rows),
            "done_strength": sum(1 for r in strength_rows if r["done"]),
            "core_logged": core_logged}


def week_label(today: date) -> str:
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d')}"
