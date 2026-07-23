#!/usr/bin/env python
"""Mac-Mini watcher: poll the board for dropped rides, analyze, publish.

Runs as a long-lived launchd KeepAlive service (com.airhart.boardwatch) via
`--loop` (internal 600 s timer; BOARDWATCH_INTERVAL_S overrides), backed by a
cron line that kickstarts the job every 10 min (no-op while running, revives
after crash/reboot). Do NOT schedule this with StartInterval on the Mini —
its gui launchd domain pends nondemand spawns (observed 2026-07-23).
For each upload with status 'received':
  1. download the zip/fit, parse with the owner-aware engine (parse_ride),
  2. write a coached report — via headless `claude -p` when logged in,
     falling back to a clean auto-generated quantitative report when not,
  3. publish to /board/reports, set the day's adherence badge (only if unset),
  4. mark the upload 'analyzed' (or 'error').

Safety rules:
  - If a report already exists for that athlete+day (visible on /board), the
    upload is marked analyzed WITHOUT publishing — never overwrite a
    hand-written report (duplicate drops land here too).
  - Badges are only written when the day has no badge yet.
  - A lockfile prevents overlapping runs.
  - The canonical archive / vault / trend CSV are NOT touched — those remain
    the MacBook import pipeline's job. This is the web-facing loop only.

Env (.env in repo root): PLAN_APP_EMAIL, PLAN_APP_PASSWORD,
optional PLAN_APP_BASE_URL, CLAUDE_BIN (default /opt/homebrew/bin/claude).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

DEFAULT_BASE = "https://garmin-data-agent.onrender.com"
LOCK = Path(tempfile.gettempdir()) / "boardwatch.lock"
CLAUDE_TIMEOUT = 240

PLAN_FILES = {"JA": "race_plan_2026.json", "RR": "race_plan_2026_robert.json"}
ATHLETE_NAMES = {"JA": "Jonathan", "RR": "Robert"}


class TransientError(Exception):
    """Failure that should NOT permanently error the upload (retry next cycle)."""


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def plan_day(athlete: str, day: str) -> dict:
    """Return {'focus':…, 'sessions':[…]} for the athlete's plan on `day`."""
    try:
        plan = json.loads((REPO / "config" / PLAN_FILES[athlete]).read_text())
        for wk in plan.get("weeks", []):
            for d in wk.get("days", []):
                if d.get("date") == day:
                    return {
                        "week_focus": wk.get("focus", ""),
                        "headline": d.get("headline", ""),
                        "sessions": [
                            {"title": s.get("title"), "targets": s.get("targets")}
                            for s in d.get("sessions", [])
                        ],
                    }
    except Exception as exc:
        log(f"plan_day error: {exc}")
    return {}


def auto_verdict(athlete: str, stats: dict) -> str:
    """Conservative fallback adherence call when Claude is unavailable."""
    z = stats.get("hr_zones") or {}
    supra = (z.get("supra_pct") or 0) + (z.get("threshold_pct") or 0)
    avg = stats.get("avg_hr") or 0
    cap = 140 if athlete == "JA" else 134
    return "plan" if (avg <= cap and supra < 5) else "off"


def fallback_report(athlete: str, stats: dict, plan: dict) -> dict:
    z = stats.get("hr_zones") or {}
    pw = stats.get("power") or {}
    drift = stats.get("hr_drift") or {}
    dur = stats.get("duration_h") or 0
    title = (f"{stats.get('location_label') or 'Ride'} {stats.get('type_label') or ''} "
             f"{stats.get('distance_rounded') or ''} mi — auto report (quantitative)")
    subline = (f"{dur:.1f} h · avg HR {stats.get('avg_hr')}, max {stats.get('max_hr')}"
               + (f" · avg {pw.get('avg_w')} W / NP {pw.get('np_w')}" if pw.get("avg_w") else ""))
    presc = "; ".join(f"{s['title']} ({s['targets']})" for s in plan.get("sessions", []) if s.get("title"))
    body = f"""<div class="rep-body">
    <h4>Auto-generated report — coached commentary pending</h4>
    This ride was analyzed automatically on upload. The numbers below are final; the coach's
    write-up follows on the next Claude pass.
    <h4>The numbers</h4>
    <ul><li>{stats.get('distance_mi')} mi · {dur:.2f} h · {stats.get('ascent_ft')} ft · avg HR
    <b>{stats.get('avg_hr')}</b>, max {stats.get('max_hr')}</li>
    <li>Power: avg {pw.get('avg_w')} W / NP {pw.get('np_w')} W · work {pw.get('total_work_kj')} kJ</li>
    <li>HR bands ({ATHLETE_NAMES[athlete]}'s anchors): {z.get('below_lt1_pct')}% easy ·
    {z.get('aero_tempo_pct')}% aerobic/tempo · {z.get('threshold_pct')}% threshold ·
    {z.get('supra_pct')}% above</li>
    <li>HR halves {drift.get('first_half_avg')}→{drift.get('second_half_avg')}
    ({'+' if (drift.get('delta') or 0) >= 0 else ''}{drift.get('delta')})</li></ul>
    <h4>Prescribed today</h4>
    {presc or plan.get('headline') or '—'}
</div>"""
    return {"title": title, "subline": subline, "body_html": body,
            "ex": auto_verdict(athlete, stats)}


def claude_report(athlete: str, stats: dict, plan: dict) -> dict | None:
    claude = os.environ.get("CLAUDE_BIN", "/opt/homebrew/bin/claude")
    prompt = f"""You are the ride-report writer for a two-athlete P2P training board. Write the
coached report for this ride in the board's established house style.

ATHLETE: {ATHLETE_NAMES[athlete]}"""
    if athlete == "RR":
        prompt += """ (Robert Raff, 60, 95 kg. Anchors: LT1 118 bpm/100 W; FTP 230 W / 2.4 W/kg
(field test 2026-07-23: 243 W for 20:01 at HR 151 avg / 157 max — Dec lab 145 bpm/190 W retired).
Threshold HR ~152. HR bands: P1<118, P2 119-133, P3 134-138, P4 139-145, P5 146+ (pre-test
bands, pending re-draw against threshold HR 152). Diesel profile: elite zero-drift durability;
limiters = W/kg and fueling; punch threshold 247 W (~107% FTP), budget <5/hr; race band
165-180 W (72-78% FTP), climbs HR<=135 cap 140.)"""
    else:
        prompt += """ (Jonathan Airhart, 91 kg / 199.8 lb targeting 195. Anchors: LT1 138 bpm/190 W,
OBLA 156/240 W, max HR 186. Limiter = riding easy days truly easy; heat inflates HR ~10-20 bpm;
Z2 = HR<=138 at 130-170 W; big-climb days HR 140-148 cap 150.)"""
    prompt += f"""

RIDE DATA (computed, trustworthy): {json.dumps(stats, default=str)}

PRESCRIBED TODAY: {json.dumps(plan)}

Write STRICT JSON only, no markdown fences, with keys:
  "title": "<Location> <Type> <NN> mi — <sharp headline verdict>",
  "subline": "duration · key numbers · verdict: on-profile|off-profile",
  "body_html": "<div class=\\"rep-body\\">...</div>" using <h4> sections in this order:
     what the ride was (vs the prescription) / what went well / what to work on / next.
     Use <ul><li> bullets, <b> for key numbers. Be specific, honest, mechanism-not-just-verdict.
     250-400 words. No fabricated data — only what's in RIDE DATA.
  "ex": one of "plan" (rode on-profile), "off" (rode off-profile), "miss".
"""
    try:
        r = subprocess.run([claude, "-p", prompt], capture_output=True, text=True,
                           timeout=CLAUDE_TIMEOUT)
        out = r.stdout.strip()
        if r.returncode != 0 or not out or "Not logged in" in out or "/login" in out[:200]:
            log(f"claude unavailable (rc={r.returncode}): {out[:120]}")
            return None
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            return None
        rep = json.loads(m.group(0))
        if not all(k in rep for k in ("title", "subline", "body_html", "ex")):
            return None
        if rep["ex"] not in ("plan", "off", "miss"):
            rep["ex"] = "off"
        if not rep["body_html"].lstrip().startswith('<div class="rep-body">'):
            rep["body_html"] = '<div class="rep-body">' + rep["body_html"] + "</div>"
        return rep
    except Exception as exc:
        log(f"claude_report error: {exc}")
        return None


def main() -> int:
    if LOCK.exists() and (datetime.now().timestamp() - LOCK.stat().st_mtime) < 3600:
        log("lock present — previous run active; exiting")
        return 0
    LOCK.write_text(str(os.getpid()))
    try:
        return run()
    finally:
        LOCK.unlink(missing_ok=True)


def run() -> int:
    load_env()
    base = (os.environ.get("PLAN_APP_BASE_URL") or DEFAULT_BASE).rstrip("/")
    email, pw = os.environ.get("PLAN_APP_EMAIL"), os.environ.get("PLAN_APP_PASSWORD")
    if not (email and pw):
        log("no credentials in .env; exiting")
        return 2
    s = requests.Session()
    s.post(f"{base}/auth/login", data={"email": email, "password": pw}, timeout=30)
    ups = s.get(f"{base}/board/uploads", timeout=30).json().get("uploads", [])
    pending = [u for u in ups if u.get("status") == "received"]
    if not pending:
        log("no pending uploads")
        return 0
    board_html = s.get(f"{base}/board", timeout=30).text
    from import_ride import extract_fits, parse_ride  # noqa: E402

    for u in pending:
        uid, fname = u["id"], u["filename"]
        log(f"processing upload {uid} ({fname})")
        try:
            raw = s.get(f"{base}/board/uploads/{uid}/download", timeout=120).content
            with tempfile.TemporaryDirectory() as td:
                fp = Path(td) / fname
                fp.write_bytes(raw)
                if fname.lower().endswith(".zip"):
                    fits = extract_fits(fp, Path(td))
                    fit = fits[0] if fits else None
                else:
                    fit = fp
                if fit is None:
                    raise RuntimeError("no FIT inside upload")
                stats = parse_ride(fit)
            athlete = "RR" if stats.get("anchors_athlete") == "partner" else "JA"
            day = stats.get("date_local")
            if f"rep-{athlete}-{day}" in board_html:
                log(f"report already exists for {athlete} {day}; marking analyzed (no overwrite)")
                s.post(f"{base}/board/uploads/{uid}/status", json={"status": "analyzed"}, timeout=30)
                continue
            plan = plan_day(athlete, day)
            rep = claude_report(athlete, stats, plan) or fallback_report(athlete, stats, plan)
            r = s.post(f"{base}/board/reports", json={
                "athlete": athlete, "day": day, "title": rep["title"],
                "subline": rep["subline"], "body_html": rep["body_html"]}, timeout=30)
            if r.status_code != 200 or not r.json().get("ok"):
                raise TransientError(f"publish failed: {r.status_code} {r.text[:120]}")
            cal = s.get(f"{base}/board/calendar", timeout=30).json().get("calendar", {})
            if not (cal.get(athlete, {}).get(day, {}) or {}).get("ex"):
                s.post(f"{base}/board/calendar",
                       json={"athlete": athlete, "day": day, "ex": rep["ex"]}, timeout=30)
            s.post(f"{base}/board/uploads/{uid}/status", json={"status": "analyzed"}, timeout=30)
            board_html += f"rep-{athlete}-{day}"  # dedupe within this run
            log(f"published {athlete} {day}: {rep['title'][:70]}")
        except (requests.RequestException, TransientError) as exc:
            # Network hiccup / server 5xx / Render cold start: leave the upload
            # 'received' so the next cycle retries instead of dead-ending it.
            log(f"upload {uid} deferred (transient, retry next cycle): {exc}")
        except Exception as exc:
            log(f"upload {uid} FAILED: {exc}")
            try:
                s.post(f"{base}/board/uploads/{uid}/status", json={"status": "error"}, timeout=30)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    # --loop: run as a long-lived KeepAlive service with an internal timer.
    # StartInterval spawns wedge in "pended" state on the Mini's gui domain
    # (observed 2026-07-23: runs=1 forever); every agent that works on that
    # box is RunAtLoad+KeepAlive, so the schedule lives here instead.
    if "--loop" in sys.argv:
        interval = int(os.environ.get("BOARDWATCH_INTERVAL_S", "600"))
        log(f"loop mode: polling every {interval}s")
        while True:
            try:
                main()
            except Exception as exc:
                log(f"loop iteration failed: {exc}")
            time.sleep(interval)
    else:
        sys.exit(main())
