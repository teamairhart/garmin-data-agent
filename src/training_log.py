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
