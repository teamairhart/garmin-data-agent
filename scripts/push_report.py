#!/usr/bin/env python
"""Publish (or update) a coached ride report on the live /board page.

Used by the import pipeline after writing a ride analysis: no redeploy needed —
the report lands in the board_reports table via POST /board/reports.

Usage:
    python scripts/push_report.py --athlete JA --day 2026-07-22 \
        --title "Memphis Road 30 mi — headline" \
        --subline "2:00 · avg 120 W · avg HR 133 · verdict: on-profile" \
        --body-file /path/to/body.html
    # optionally also set the day's calendar badge:
    #   --ex plan|off|miss    --loc MEM|PC|OTH|TRV|OFF

Auth: PLAN_APP_EMAIL / PLAN_APP_PASSWORD from the project .env (same creds as
tick_session.py). Prints one JSON line; exit 0 on success.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://garmin-data-agent.onrender.com"


def _emit(status: str, **extra) -> None:
    print(json.dumps({"status": status, **extra}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--athlete", required=True, choices=["JA", "RR"])
    ap.add_argument("--day", required=True, help="YYYY-MM-DD")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subline", default="")
    ap.add_argument("--body-file", required=True, help="HTML file: <div class=\"rep-body\">…</div>")
    ap.add_argument("--ex", choices=["none", "plan", "off", "miss"], help="Also set the day's badge")
    ap.add_argument("--loc", help="Also set the day's location (MEM/PC/OTH/TRV/OFF)")
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except Exception:
        pass

    base = (args.base_url or os.environ.get("PLAN_APP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    email, password = os.environ.get("PLAN_APP_EMAIL"), os.environ.get("PLAN_APP_PASSWORD")
    if not (email and password):
        _emit("error", reason="no_credentials", hint="Set PLAN_APP_EMAIL/PLAN_APP_PASSWORD in .env")
        return 2

    body = Path(args.body_file).read_text(encoding="utf-8")
    s = requests.Session()
    r = s.post(f"{base}/auth/login", data={"email": email, "password": password},
               timeout=30, allow_redirects=True)
    if r.status_code >= 400:
        _emit("error", reason="login_failed", status_code=r.status_code)
        return 2

    r = s.post(f"{base}/board/reports", json={
        "athlete": args.athlete, "day": args.day, "title": args.title,
        "subline": args.subline, "body_html": body}, timeout=30)
    out = {}
    try:
        out = r.json()
    except Exception:
        pass
    if r.status_code != 200 or not out.get("ok"):
        _emit("error", reason="publish_failed", status_code=r.status_code, response=out)
        return 1

    if args.ex or args.loc:
        patch = {"athlete": args.athlete, "day": args.day}
        if args.ex:
            patch["ex"] = args.ex
        if args.loc:
            patch["loc"] = args.loc
        s.post(f"{base}/board/calendar", json=patch, timeout=30)

    _emit("published", athlete=args.athlete, day=args.day, title=args.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
