"""Shared P2P accountability board: calendar state, ride reports, uploads.

Backs the /board page. All state is server-side SQLite (persistent disk on
Render) so Jonathan's and Robert's taps and reports are shared truth:
  - board_calendar: per-athlete per-day location (MEM/PC/OTH/TRV/OFF) and
    execution badge (none/plan/off/miss).
  - board_reports: coached ride reports (HTML bodies) rendered into the page;
    new ones arrive via POST /board/reports (see scripts/push_report.py) so
    publishing a report never requires a redeploy.
  - board_uploads: ride files dropped on the page, stored on the persistent
    disk for the Mac-side import pipeline to pull.

First boot seeds reports + this week's calendar from config/board_seed/.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from src.auth import get_db_connection

SEED_DIR = Path(__file__).resolve().parents[1] / "config" / "board_seed"

ATHLETES = ("JA", "RR")
LOC_STATES = {"JA": ("MEM", "PC", "TRV", "OFF"), "RR": ("PC", "OTH", "TRV", "OFF")}
EX_STATES = ("none", "plan", "off", "miss")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def upload_dir() -> Path:
    """Board uploads live next to the SQLite file (Render persistent disk)."""
    db_path = os.environ.get("DATABASE_PATH")
    base = Path(db_path).parent if db_path else Path("uploads")
    d = base / "board_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_board_tables() -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS board_calendar (
            athlete TEXT NOT NULL,
            day TEXT NOT NULL,
            loc TEXT,
            ex TEXT,
            updated_by INTEGER,
            updated_at TEXT,
            PRIMARY KEY (athlete, day))"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS board_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete TEXT NOT NULL,
            day TEXT NOT NULL,
            title TEXT NOT NULL,
            subline TEXT,
            body_html TEXT NOT NULL,
            created_at TEXT,
            UNIQUE (athlete, day))"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS board_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            size_bytes INTEGER,
            uploaded_by INTEGER,
            uploaded_at TEXT,
            status TEXT NOT NULL DEFAULT 'received')"""
    )
    conn.commit()
    conn.close()
    _seed_if_empty()


def _seed_if_empty() -> None:
    meta_path = SEED_DIR / "meta.json"
    if not meta_path.exists():
        return
    with meta_path.open(encoding="utf-8") as fh:
        meta = json.load(fh)
    conn = get_db_connection()
    cur = conn.cursor()
    if cur.execute("SELECT COUNT(*) FROM board_reports").fetchone()[0] == 0:
        for r in meta.get("reports", []):
            body = (SEED_DIR / r["body_file"]).read_text(encoding="utf-8")
            cur.execute(
                "INSERT OR IGNORE INTO board_reports (athlete, day, title, subline, body_html, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (r["athlete"], r["day"], r["title"], r.get("subline", ""), body, _now()),
            )
    if cur.execute("SELECT COUNT(*) FROM board_calendar").fetchone()[0] == 0:
        for c in meta.get("calendar", []):
            cur.execute(
                "INSERT OR IGNORE INTO board_calendar (athlete, day, loc, ex, updated_at) VALUES (?,?,?,?,?)",
                (c["athlete"], c["day"], c.get("loc"), c.get("ex"), _now()),
            )
    conn.commit()
    conn.close()


def get_calendar() -> dict:
    conn = get_db_connection()
    rows = conn.execute("SELECT athlete, day, loc, ex FROM board_calendar").fetchall()
    conn.close()
    out: dict = {a: {} for a in ATHLETES}
    for r in rows:
        if r["athlete"] in out:
            out[r["athlete"]][r["day"]] = {"loc": r["loc"], "ex": r["ex"]}
    return out


def set_calendar_day(athlete: str, day: str, loc: str | None = None,
                     ex: str | None = None, user_id: int | None = None) -> dict:
    if athlete not in ATHLETES:
        raise ValueError("bad athlete")
    if not DAY_RE.match(day or ""):
        raise ValueError("bad day")
    if loc is not None and loc not in LOC_STATES[athlete]:
        raise ValueError("bad loc")
    if ex is not None and ex not in EX_STATES:
        raise ValueError("bad ex")
    conn = get_db_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT loc, ex FROM board_calendar WHERE athlete=? AND day=?", (athlete, day)
    ).fetchone()
    new_loc = loc if loc is not None else (row["loc"] if row else None)
    new_ex = ex if ex is not None else (row["ex"] if row else None)
    cur.execute(
        "INSERT INTO board_calendar (athlete, day, loc, ex, updated_by, updated_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(athlete, day) DO UPDATE SET loc=excluded.loc, ex=excluded.ex,"
        " updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (athlete, day, new_loc, new_ex, user_id, _now()),
    )
    conn.commit()
    conn.close()
    return {"athlete": athlete, "day": day, "loc": new_loc, "ex": new_ex}


def list_reports() -> list[dict]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT athlete, day, title, subline, body_html FROM board_reports ORDER BY day DESC, athlete ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_report(athlete: str, day: str, title: str, subline: str, body_html: str) -> None:
    if athlete not in ATHLETES:
        raise ValueError("bad athlete")
    if not DAY_RE.match(day or ""):
        raise ValueError("bad day")
    if not title or not body_html:
        raise ValueError("title and body_html required")
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO board_reports (athlete, day, title, subline, body_html, created_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(athlete, day) DO UPDATE SET title=excluded.title, subline=excluded.subline,"
        " body_html=excluded.body_html, created_at=excluded.created_at",
        (athlete, day, title, subline or "", body_html, _now()),
    )
    conn.commit()
    conn.close()


def record_upload(filename: str, stored_path: str, size_bytes: int, user_id: int | None) -> int:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO board_uploads (filename, stored_path, size_bytes, uploaded_by, uploaded_at) VALUES (?,?,?,?,?)",
        (filename, stored_path, size_bytes, user_id, _now()),
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid


def list_uploads() -> list[dict]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT bu.id, bu.filename, bu.size_bytes, bu.uploaded_by, bu.uploaded_at, bu.status,"
        " COALESCE(u.name, '?') AS who"
        " FROM board_uploads bu LEFT JOIN users u ON u.id = bu.uploaded_by"
        " ORDER BY bu.id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upload(uid: int) -> dict | None:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM board_uploads WHERE id=?", (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_upload_status(uid: int, status: str) -> None:
    conn = get_db_connection()
    conn.execute("UPDATE board_uploads SET status=? WHERE id=?", (status, uid))
    conn.commit()
    conn.close()
