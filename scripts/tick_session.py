#!/usr/bin/env python3
"""Tick (or untick) a race-plan session on the live plan web app.

Logs into the Flask app at ``PLAN_APP_BASE_URL`` using ``PLAN_APP_EMAIL`` /
``PLAN_APP_PASSWORD`` (read from the environment or the repo ``.env``) and POSTs
``/plan/toggle`` for the given session id. Backs the garmin-ride-import skill so
the matching ``<date>-ride`` session is checked off automatically after a ride
is imported.

Fails soft by design: if no credentials are configured it prints a ``skipped``
result and exits with code 2 so the caller can fall back to asking the user to
tick the box manually. Any login/network error exits 1 with a ``error`` result.
Output is always a single JSON object on stdout.

Usage:
    python scripts/tick_session.py 2026-06-17-ride
    python scripts/tick_session.py 2026-06-17-ride --uncheck --notes "shifted"

Required env (put in .env, which is gitignored):
    PLAN_APP_EMAIL     login email for the plan web app
    PLAN_APP_PASSWORD  login password
Optional:
    PLAN_APP_BASE_URL  default https://garmin-data-agent.onrender.com
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_BASE_URL = "https://garmin-data-agent.onrender.com"


def _emit(status: str, **extra) -> None:
    """Print a single-line JSON result for the caller to parse."""
    print(json.dumps({"status": status, **extra}))


def main() -> int:
    ap = argparse.ArgumentParser(description="Tick a plan session on the live web app.")
    ap.add_argument("item_id", help="Plan session id, e.g. 2026-06-17-ride")
    ap.add_argument("--uncheck", action="store_true", help="Uncheck instead of check")
    ap.add_argument("--notes", default=None, help="Optional note stored with the completion")
    ap.add_argument("--base-url", default=None, help="Override the app base URL")
    ap.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout (seconds)")
    args = ap.parse_args()

    # Load .env from the repo root without clobbering already-set env vars.
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except Exception:
        pass

    base_url = (args.base_url or os.environ.get("PLAN_APP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    email = os.environ.get("PLAN_APP_EMAIL")
    password = os.environ.get("PLAN_APP_PASSWORD")

    if not email or not password:
        _emit(
            "skipped",
            reason="no_credentials",
            item_id=args.item_id,
            hint="Set PLAN_APP_EMAIL and PLAN_APP_PASSWORD in .env to enable auto-tick.",
        )
        return 2

    import requests

    completed = not args.uncheck
    s = requests.Session()
    try:
        # 1) Log in. The Flask route 302-redirects on success and re-renders the
        #    login page (200) on bad credentials.
        login = s.post(
            f"{base_url}/auth/login",
            data={"email": email, "password": password},
            timeout=args.timeout,
            allow_redirects=False,
        )
        if login.status_code not in (301, 302, 303):
            _emit(
                "error",
                reason="login_failed",
                item_id=args.item_id,
                http_status=login.status_code,
                message="Login did not redirect — check PLAN_APP_EMAIL/PLAN_APP_PASSWORD.",
            )
            return 1

        # 2) Toggle the completion (JSON body; session cookie carries auth).
        toggle = s.post(
            f"{base_url}/plan/toggle",
            json={"item_id": args.item_id, "completed": completed, "notes": args.notes},
            timeout=args.timeout,
        )
        if toggle.status_code == 401:
            _emit(
                "error",
                reason="login_required",
                item_id=args.item_id,
                message="Not authenticated after login (unexpected).",
            )
            return 1
        if toggle.status_code != 200:
            _emit(
                "error",
                reason="toggle_failed",
                item_id=args.item_id,
                http_status=toggle.status_code,
                body=toggle.text[:300],
            )
            return 1

        data = toggle.json()
        if not data.get("ok"):
            _emit("error", reason="toggle_rejected", item_id=args.item_id, body=data)
            return 1

        _emit(
            "ticked" if completed else "unticked",
            item_id=args.item_id,
            summary=data.get("summary"),
        )
        return 0
    except requests.RequestException as exc:
        _emit("error", reason="network", item_id=args.item_id, message=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
