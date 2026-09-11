from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from src.auth import get_db_connection


def init_training_tables() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS workout_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            planned_date TEXT NOT NULL,
            workout_name TEXT NOT NULL,
            workout_type TEXT,
            location TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            duration_minutes INTEGER,
            rpe INTEGER,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, planned_date, workout_name),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS gym_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_date TEXT NOT NULL,
            title TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS gym_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            exercise_name TEXT NOT NULL,
            set_number INTEGER NOT NULL,
            reps INTEGER,
            weight REAL,
            notes TEXT,
            FOREIGN KEY (session_id) REFERENCES gym_sessions (id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()


def upsert_workout_log(
    user_id: int,
    planned_date: str,
    workout_name: str,
    workout_type: str | None,
    location: str | None,
    status: str,
    duration_minutes: int | None,
    rpe: int | None,
    notes: str | None,
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO workout_logs (
            user_id,
            planned_date,
            workout_name,
            workout_type,
            location,
            status,
            duration_minutes,
            rpe,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, planned_date, workout_name)
        DO UPDATE SET
            workout_type = excluded.workout_type,
            location = excluded.location,
            status = excluded.status,
            duration_minutes = excluded.duration_minutes,
            rpe = excluded.rpe,
            notes = excluded.notes,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            planned_date,
            workout_name,
            workout_type,
            location,
            status,
            duration_minutes,
            rpe,
            notes,
        ),
    )
    conn.commit()
    conn.close()


def get_workout_logs(user_id: int) -> dict[str, dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT planned_date, workout_name, workout_type, location, status, duration_minutes, rpe, notes
        FROM workout_logs
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    conn.close()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['planned_date']}|{row['workout_name']}"
        result[key] = dict(row)
    return result


def create_gym_session(
    user_id: int,
    session_date: str,
    title: str | None,
    notes: str | None,
    sets: list[dict[str, Any]],
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO gym_sessions (user_id, session_date, title, notes)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, session_date, title, notes),
    )
    session_id = cursor.lastrowid

    for index, gym_set in enumerate(sets, start=1):
        exercise_name = (gym_set.get("exercise_name") or "").strip()
        if not exercise_name:
            continue
        cursor.execute(
            """
            INSERT INTO gym_sets (session_id, exercise_name, set_number, reps, weight, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                exercise_name,
                gym_set.get("set_number") or index,
                gym_set.get("reps"),
                gym_set.get("weight"),
                gym_set.get("notes"),
            ),
        )

    conn.commit()
    conn.close()


def list_recent_gym_sessions(user_id: int, limit: int = 8) -> list[dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    sessions = cursor.execute(
        """
        SELECT id, session_date, title, notes, created_at
        FROM gym_sessions
        WHERE user_id = ?
        ORDER BY session_date DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()

    session_ids = [row["id"] for row in sessions]
    sets_by_session: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if session_ids:
        placeholders = ",".join("?" for _ in session_ids)
        sets = cursor.execute(
            f"""
            SELECT session_id, exercise_name, set_number, reps, weight, notes
            FROM gym_sets
            WHERE session_id IN ({placeholders})
            ORDER BY session_id DESC, exercise_name, set_number
            """,
            session_ids,
        ).fetchall()
        for gym_set in sets:
            sets_by_session[gym_set["session_id"]].append(dict(gym_set))

    conn.close()

    result: list[dict[str, Any]] = []
    for session_row in sessions:
        entry = dict(session_row)
        entry["sets"] = sets_by_session.get(session_row["id"], [])
        result.append(entry)
    return result


# ---------------------------------------------------------------- strength log (Workout log grammar)

from datetime import date as _date, timedelta as _timedelta

from src.strength_log import ParsedSession, best_set, format_sets, load_exercise_library

_SESSION_EXTRA_COLUMNS = {
    "location": "TEXT", "bodyweight": "REAL", "duration_minutes": "INTEGER", "rpe": "REAL",
    "session_type": "TEXT", "source": "TEXT", "updated_at": "TIMESTAMP",
}
_SET_EXTRA_COLUMNS = {
    "exercise_order": "INTEGER", "typed_name": "TEXT", "category": "TEXT", "load_kind": "TEXT",
    "added_lb": "REAL", "duration_s": "INTEGER", "set_rpe": "REAL", "is_amrap": "INTEGER", "raw": "TEXT",
}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, decl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_strength_columns() -> None:
    """Widen the original gym tables (idempotent; safe on the Render persistent-disk DB)."""
    conn = get_db_connection()
    _ensure_columns(conn, "gym_sessions", _SESSION_EXTRA_COLUMNS)
    _ensure_columns(conn, "gym_sets", _SET_EXTRA_COLUMNS)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gym_sessions_user_date ON gym_sessions (user_id, session_date)"
    )
    conn.commit()
    conn.close()


def upsert_gym_session(user_id: int, sess: ParsedSession, source: str = "api") -> dict[str, Any]:
    """Insert or replace a session keyed by (user, date, title). Sets are replaced wholesale."""
    conn = get_db_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM gym_sessions WHERE user_id = ? AND session_date = ? AND title = ?",
        (user_id, sess.session_date, sess.title),
    ).fetchone()
    created = row is None
    if created:
        cur.execute(
            """INSERT INTO gym_sessions (user_id, session_date, title, notes, location, bodyweight,
                   duration_minutes, rpe, session_type, source, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (user_id, sess.session_date, sess.title, sess.notes, sess.location, sess.bodyweight,
             sess.duration_minutes, sess.rpe, sess.session_type, source),
        )
        session_id = cur.lastrowid
    else:
        session_id = row["id"]
        cur.execute(
            """UPDATE gym_sessions SET notes = ?, location = ?, bodyweight = ?, duration_minutes = ?,
                   rpe = ?, session_type = ?, source = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (sess.notes, sess.location, sess.bodyweight, sess.duration_minutes, sess.rpe,
             sess.session_type, source, session_id),
        )
        cur.execute("DELETE FROM gym_sets WHERE session_id = ?", (session_id,))
    n_sets = 0
    for order, ex in enumerate(sess.exercises, start=1):
        for s in ex.sets:
            n_sets += 1
            cur.execute(
                """INSERT INTO gym_sets (session_id, exercise_name, set_number, reps, weight, notes,
                       exercise_order, typed_name, category, load_kind, added_lb, duration_s, set_rpe, is_amrap, raw)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, ex.canonical, s.set_number, s.reps, s.load_lb, None, order, ex.name, ex.category,
                 s.load_kind, s.added_lb, s.duration_s, s.rpe, 1 if s.is_amrap else 0, s.raw),
            )
    conn.commit()
    conn.close()
    return {"id": session_id, "created": created, "session_date": sess.session_date, "title": sess.title,
            "exercises": len(sess.exercises), "sets": n_sets, "warnings": list(sess.warnings)}


def _label(day: str) -> str:
    try:
        return _date.fromisoformat(day).strftime("%a %b %d").replace(" 0", " ")
    except ValueError:
        return day


def list_gym_sessions(user_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    """All sessions newest-first, exercises in logged order, with per-exercise best e1RM and PR flags."""
    conn = get_db_connection()
    cur = conn.cursor()
    sql = """SELECT id, session_date, title, notes, location, bodyweight, duration_minutes, rpe,
                    session_type, source, created_at
             FROM gym_sessions WHERE user_id = ? ORDER BY session_date DESC, id DESC"""
    params: list[Any] = [user_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    sessions = [dict(r) for r in cur.execute(sql, params).fetchall()]
    ids = [s["id"] for s in sessions]
    sets_by_session: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        placeholders = ",".join("?" for _ in ids)
        for r in cur.execute(
            f"""SELECT session_id, exercise_name, typed_name, category, set_number, reps, weight AS load_lb,
                       exercise_order, load_kind, added_lb, duration_s, set_rpe, is_amrap, raw
                FROM gym_sets WHERE session_id IN ({placeholders}) ORDER BY session_id, id""",
            ids,
        ).fetchall():
            sets_by_session[r["session_id"]].append(dict(r))
    conn.close()

    for s in sessions:
        s["label"] = _label(s["session_date"])
        s["session_type"] = s.get("session_type") or "strength"
        groups: dict[str, dict[str, Any]] = {}
        for r in sets_by_session.get(s["id"], []):
            r["load_kind"] = r.get("load_kind") or "lb"
            g = groups.get(r["exercise_name"])
            if g is None:
                g = {"name": r["exercise_name"], "category": r.get("category") or "other",
                     "order": r.get("exercise_order") or len(groups) + 1, "sets": []}
                groups[r["exercise_name"]] = g
            g["sets"].append(r)
        exercises = sorted(groups.values(), key=lambda g: g["order"])
        for g in exercises:
            g["best"] = best_set(g["sets"])
            g["sets_text"] = format_sets(g["sets"])
            g["volume_lb"] = round(sum((x["load_lb"] or 0) * (x["reps"] or 0) for x in g["sets"]
                                      if x["load_kind"] == "lb"))
        s["exercises"] = exercises
        s["volume_lb"] = sum(g["volume_lb"] for g in exercises)
        s["core_count"] = sum(1 for g in exercises if g["category"] == "core")
        s["is_core_session"] = s["session_type"] == "core" or s["core_count"] > 0

    # PR pass: chronological, first-ever and best-e1RM-so-far per exercise
    seen_best: dict[str, float] = {}
    for s in reversed(sessions):
        for g in s["exercises"]:
            g["first"] = g["name"] not in seen_best
            e1 = g["best"]["e1rm"] if g["best"] else None
            prev = seen_best.get(g["name"])
            g["pr"] = bool(e1 is not None and prev is not None and e1 > prev)
            if e1 is not None and (prev is None or e1 > prev):
                seen_best[g["name"]] = e1
            elif prev is None:
                seen_best[g["name"]] = -1.0
    return sessions


def _week_bounds(today: _date) -> tuple[_date, _date]:
    start = today - _timedelta(days=today.weekday())      # Monday
    return start, start + _timedelta(days=6)


def strength_summary(user_id: int, today: _date, core_target: int = 5,
                     sessions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sessions = sessions if sessions is not None else list_gym_sessions(user_id)
    lib = load_exercise_library()
    tracked = {e["name"] for e in lib["entries"] if e.get("track_e1rm")}

    lifts: dict[str, dict[str, Any]] = {}
    for s in sessions:                       # newest first
        for g in s["exercises"]:
            if g["name"] not in tracked or not g["best"]:
                continue
            L = lifts.setdefault(g["name"], {"name": g["name"], "category": g["category"], "n_sessions": 0,
                                             "best_e1rm": None, "latest_e1rm": None})
            L["n_sessions"] += 1
            if L["latest_e1rm"] is None:
                L["latest_e1rm"], L["latest_date"] = g["best"]["e1rm"], s["session_date"]
                L["latest_load"], L["latest_reps"] = g["best"]["load_lb"], g["best"]["reps"]
            if L["best_e1rm"] is None or g["best"]["e1rm"] > L["best_e1rm"]:
                L["best_e1rm"], L["best_date"] = g["best"]["e1rm"], s["session_date"]
                L["best_load"], L["best_reps"] = g["best"]["load_lb"], g["best"]["reps"]
    order = {"Bench press": 0, "Trap-bar deadlift": 1}
    lift_list = sorted(lifts.values(), key=lambda L: (order.get(L["name"], 9), -(L["best_e1rm"] or 0)))

    wk_start, wk_end = _week_bounds(today)
    in_week = [s for s in sessions if wk_start.isoformat() <= s["session_date"] <= wk_end.isoformat()]
    week = {"start": wk_start.isoformat(), "end": wk_end.isoformat(),
            "gym_sessions": sum(1 for s in in_week if s["session_type"] != "core"),
            "core_sessions": sum(1 for s in in_week if s["is_core_session"]),
            "sessions": in_week}

    # consecutive prior-or-current weeks meeting the core target
    by_week: dict[str, int] = defaultdict(int)
    for s in sessions:
        if s["is_core_session"]:
            d = _date.fromisoformat(s["session_date"])
            by_week[_week_bounds(d)[0].isoformat()] += 1
    streak = 0
    cursor = wk_start if by_week.get(wk_start.isoformat(), 0) >= core_target else wk_start - _timedelta(days=7)
    while by_week.get(cursor.isoformat(), 0) >= core_target:
        streak += 1
        cursor -= _timedelta(days=7)

    latest_bw = None
    for s in sessions:
        if s.get("bodyweight"):
            latest_bw = {"value": s["bodyweight"], "date": s["session_date"]}
            break

    return {
        "lifts": lift_list,
        "bench": lifts.get("Bench press"),
        "trapbar": lifts.get("Trap-bar deadlift"),
        "week": week,
        "core_target": core_target,
        "core_weeks_at_target": streak,
        "latest_bodyweight": latest_bw,
        "total_sessions": len(sessions),
        "first_date": sessions[-1]["session_date"] if sessions else None,
        "last_date": sessions[0]["session_date"] if sessions else None,
    }
