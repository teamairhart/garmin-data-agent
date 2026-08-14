#!/usr/bin/env python
"""Push data/fitness_trends.json to the live /board Fitness Trends section.

No redeploy needed — the payload lands in the board_trends table via
POST /board/trends. Regenerate the payload first:

    python scripts/fitness_trends.py --sweep --aggregate
    python scripts/push_trends.py

Auth: PLAN_APP_EMAIL / PLAN_APP_PASSWORD from the project .env (same as
push_report.py). Prints one JSON line; exit 0 on success.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://garmin-data-agent.onrender.com"
DEFAULT_PAYLOAD = Path(__file__).resolve().parents[1] / "data" / "fitness_trends.json"


def _emit(status: str, **extra) -> None:
    print(json.dumps({"status": status, **extra}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
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

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    s = requests.Session()
    r = s.post(f"{base}/auth/login", data={"email": email, "password": password},
               timeout=30, allow_redirects=True)
    if r.status_code >= 400:
        _emit("error", reason="login_failed", status_code=r.status_code)
        return 2

    r = s.post(f"{base}/board/trends", json=payload, timeout=30)
    out = {}
    try:
        out = r.json()
    except Exception:
        pass
    if r.status_code != 200 or not out.get("ok"):
        _emit("error", reason="push_failed", status_code=r.status_code, response=out)
        return 1

    _emit("published", generated=payload.get("generated"),
          athletes=list(payload.get("athletes", {})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
