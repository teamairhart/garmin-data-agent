#!/usr/bin/env python
"""Push gym sessions from the Obsidian Workout log to the live /strength page.

Parses ~/Vault/Fitness/Workout log.md with src/strength_log.py (the same parser the site uses),
then upserts every session (or only those on/after --since) through POST /strength/sessions.
Idempotent: a session is keyed by (date, session name), so re-running just replaces it.

Usage:
    python scripts/push_workouts.py                 # push everything in the note
    python scripts/push_workouts.py --since 2026-09-01
    python scripts/push_workouts.py --dry-run       # parse only, show what would be sent
    python scripts/push_workouts.py --file /path/to/other.md

Auth: PLAN_APP_EMAIL / PLAN_APP_PASSWORD from the project .env (same creds as push_report.py).
Prints one JSON line; exit 0 on success, 1 on publish failure, 2 on config/parse failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.strength_log import parse_workout_log, format_sets  # noqa: E402

DEFAULT_BASE_URL = "https://garmin-data-agent.onrender.com"
DEFAULT_FILE = Path.home() / "Vault" / "Fitness" / "Workout log.md"


def _emit(status: str, **extra) -> None:
    print(json.dumps({"status": status, **extra}, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    ap.add_argument("--since", help="YYYY-MM-DD: only sessions on/after this date")
    ap.add_argument("--dry-run", action="store_true", help="parse and print; don't push")
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    if not path.exists():
        _emit("error", reason="file_not_found", file=str(path))
        return 2
    text = path.read_text(encoding="utf-8")
    sessions = parse_workout_log(text)
    if args.since:
        sessions = [s for s in sessions if s.session_date >= args.since]
    if not sessions:
        _emit("error", reason="no_sessions_parsed", file=str(path))
        return 2

    warnings = [f"{s.session_date} {s.title}: {w}" for s in sessions for w in s.warnings]
    if args.dry_run:
        for s in sessions:
            print(f"{s.session_date} · {s.title}" + (f" · {s.location}" if s.location else "")
                  + (f" · bw {s.bodyweight:g}" if s.bodyweight else ""))
            for ex in s.exercises:
                flag = "" if ex.known else "  (unknown name — logged as typed)"
                print(f"   - {ex.canonical}: {format_sets([vars(x) for x in ex.sets])}{flag}")
            if s.notes:
                print(f"   Notes: {s.notes.splitlines()[0][:80]}")
        _emit("dry_run", sessions=len(sessions), warnings=warnings)
        return 0

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    import requests

    base = (args.base_url or os.environ.get("PLAN_APP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    email, password = os.environ.get("PLAN_APP_EMAIL"), os.environ.get("PLAN_APP_PASSWORD")
    if not (email and password):
        _emit("error", reason="no_credentials", hint="Set PLAN_APP_EMAIL/PLAN_APP_PASSWORD in .env")
        return 2

    s = requests.Session()
    r = s.post(f"{base}/auth/login", data={"email": email, "password": password}, timeout=60, allow_redirects=True)
    if r.status_code >= 400:
        _emit("error", reason="login_failed", status_code=r.status_code)
        return 2
    r = s.post(f"{base}/strength/sessions", json={"sessions": [x.to_dict() for x in sessions]}, timeout=60)
    out: dict = {}
    try:
        out = r.json()
    except Exception:
        pass
    if r.status_code != 200 or not out.get("ok"):
        _emit("error", reason="publish_failed", status_code=r.status_code, response=out)
        return 1
    results = out.get("results", [])
    _emit("published", sessions=len(results),
          created=sum(1 for x in results if x.get("created")),
          replaced=sum(1 for x in results if not x.get("created")),
          warnings=warnings, url=f"{base}/strength")
    return 0


if __name__ == "__main__":
    sys.exit(main())
