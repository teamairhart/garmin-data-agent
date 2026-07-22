#!/usr/bin/env python
"""Fetch recent ride(s) from Garmin Connect straight into ~/Downloads.

Replaces the manual website-download step of the garmin-ride-import flow: the
zip lands in ~/Downloads named `<activityId>.zip`, exactly like a manual
download, so `import_ride.py scan/commit` works unchanged downstream.

Auth (unofficial garminconnect/garth client):
  1. OAuth tokens in ~/.garminconnect (created by `--login`, last ~1 year) —
     preferred; no password stored anywhere.
  2. Fallback: GARMIN_EMAIL / GARMIN_PASSWORD in the project .env for silent
     re-login when tokens expire (MFA accounts still need `--login`).

Usage:
    python scripts/garmin_fetch.py --login      # one-time interactive login (run in a terminal; prompts for MFA if enabled)
    python scripts/garmin_fetch.py              # fetch new cycling activities from the last 3 days
    python scripts/garmin_fetch.py --days 7     # look back further
    python scripts/garmin_fetch.py --force      # re-download even if already imported

Prints one JSON line per run: {"status": ..., "fetched": [...], "skipped": [...]}.
Already-imported rides are detected via `<activityId>.zip` in the archive's
_rename_map.csv (and zips already sitting in ~/Downloads are not re-fetched).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

TOKEN_DIR = Path.home() / ".garminconnect"
DOWNLOADS = Path.home() / "Downloads"
RENAME_MAPS = [
    Path.home() / "DevProjects" / "Fitness Data" / "Garmin_Data" / "_rename_map.csv",
    Path.home() / "DevProjects" / "Fitness Data" / "Partner_Garmin" / "_rename_map.csv",
]
CYCLING_TYPES = {
    "cycling", "road_biking", "mountain_biking", "gravel_cycling",
    "indoor_cycling", "virtual_ride", "cyclocross", "e_bike_mountain",
}


def _emit(status: str, **extra) -> None:
    print(json.dumps({"status": status, **extra}))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except Exception:
        pass


def _imported_ids() -> set[str]:
    ids: set[str] = set()
    for m in RENAME_MAPS:
        if not m.exists():
            continue
        with m.open() as fh:
            for row in csv.DictReader(fh):
                old = (row.get("old_name") or "").strip()
                if old.endswith(".zip"):
                    ids.add(old[:-4])
    return ids


def _client(interactive: bool):
    import os

    from garminconnect import Garmin

    # 1) resume from saved tokens
    if TOKEN_DIR.exists():
        try:
            g = Garmin()
            g.login(str(TOKEN_DIR))
            return g
        except Exception:
            pass  # stale tokens — fall through to credential login

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if interactive and not (email and password):
        email = input("Garmin Connect email: ").strip()
        import getpass

        password = getpass.getpass("Garmin Connect password: ")
    if not (email and password):
        _emit(
            "error",
            reason="no_auth",
            hint="Run `python scripts/garmin_fetch.py --login` once in a terminal, "
            "or set GARMIN_EMAIL/GARMIN_PASSWORD in .env.",
        )
        sys.exit(2)

    g = Garmin(email=email, password=password, return_on_mfa=True)
    try:
        result, state = g.login()
        if result == "needs_mfa":
            if not interactive:
                _emit(
                    "error",
                    reason="mfa_required",
                    hint="Run `python scripts/garmin_fetch.py --login` in a terminal to enter the MFA code once; tokens are then reused silently.",
                )
                sys.exit(2)
            code = input("MFA code: ").strip()
            g.resume_login(state, code)
    except Exception as e:
        msg = str(e)
        reason = "rate_limited" if "429" in msg else "login_failed"
        _emit(
            "error",
            reason=reason,
            detail=msg[:300],
            hint="Garmin rate-limits login attempts by IP — wait 30-60 min and retry `--login`. "
            "Credentials are only needed for login; once tokens exist this never runs again for ~a year.",
        )
        sys.exit(2)

    # Login can fail without raising (e.g. all transports 429) — verify before saving tokens.
    if getattr(g, "garth", None) is None:
        _emit(
            "error",
            reason="rate_limited",
            detail="Login did not complete (no session established) — Garmin likely rate-limited the attempt (429).",
            hint="Wait 30-60 min and retry `--login`, or retry from a different network (phone hotspot).",
        )
        sys.exit(2)
    g.garth.dump(str(TOKEN_DIR))
    return g


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch recent Garmin rides into ~/Downloads.")
    ap.add_argument("--login", action="store_true", help="Interactive first-time login (saves tokens)")
    ap.add_argument("--days", type=int, default=3, help="Look-back window (default 3)")
    ap.add_argument("--force", action="store_true", help="Fetch even if already imported")
    ap.add_argument("--all-types", action="store_true", help="Include non-cycling activities")
    args = ap.parse_args()

    _load_env()
    g = _client(interactive=args.login)
    if args.login:
        _emit("logged_in", tokens=str(TOKEN_DIR))

    from garminconnect import Garmin

    start = (dt.date.today() - dt.timedelta(days=args.days)).isoformat()
    end = dt.date.today().isoformat()
    acts = g.get_activities_by_date(start, end)
    done = _imported_ids()
    fetched, skipped = [], []
    for a in acts:
        aid = str(a.get("activityId"))
        akey = (a.get("activityType") or {}).get("typeKey", "?")
        info = {
            "id": aid,
            "type": akey,
            "start": a.get("startTimeLocal"),
            "name": a.get("activityName"),
            "distance_mi": round((a.get("distance") or 0) / 1609.34, 1),
            "duration_min": round((a.get("duration") or 0) / 60, 1),
        }
        if not args.all_types and akey not in CYCLING_TYPES:
            skipped.append({**info, "reason": "not_cycling"})
            continue
        dest = DOWNLOADS / f"{aid}.zip"
        if not args.force and aid in done:
            skipped.append({**info, "reason": "already_imported"})
            continue
        if not args.force and dest.exists():
            skipped.append({**info, "reason": "zip_already_in_downloads"})
            continue
        payload = g.download_activity(aid, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
        dest.write_bytes(payload)
        info["saved_to"] = str(dest)
        fetched.append(info)

    _emit("ok", fetched=fetched, skipped=skipped, window_days=args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
