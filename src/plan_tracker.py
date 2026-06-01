"""Interactive race-plan tracking: completion state + plan loader.

Backs the /plan page. Stores per-user check-offs in SQLite (persistent disk on
Render), and loads the structured plan from config/race_plan_2026.json.
Mirrors the sqlite pattern in training_log.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.auth import get_db_connection

PLAN_PATH = Path(__file__).resolve().parents[1] / "config" / "race_plan_2026.json"


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


def load_plan() -> dict[str, Any]:
    """Load the structured plan JSON (empty skeleton if missing)."""
    if not PLAN_PATH.exists():
        return {"meta": {}, "weeks": [], "templates": {}}
    with PLAN_PATH.open(encoding="utf-8") as fh:
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
