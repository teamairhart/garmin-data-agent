#!/usr/bin/env python3
"""Aerobic-efficiency trend: are you getting FASTER at the same heart rate?

For an HR-only athlete on a repeated course, the cleanest fitness signal is
**pace at a controlled heart rate**. Rising speed at a fixed sub-LT1 HR (or the
same speed at a lower HR) = improving aerobic efficiency — "more powerful at this
heart rate zone" without a power meter.

For every matching ride this computes, time-weighted over *moving* records
(speed > 3 mph, to drop stoplights/coasting):

  - speed_at_hr135  : speed predicted at exactly 135 bpm from a within-ride linear
                      fit of speed~HR over 125-145 bpm. The headline metric — it
                      normalizes for how hard each ride sat, so rides are
                      apples-to-apples. (needs >=10 min in 125-145 to be valid)
  - band_speed      : mean moving speed while HR is in [130,140) bpm
  - min_in_band     : minutes of data in that band (confidence)
  - EF              : avg_moving_speed / avg_HR * 100 (whole-ride efficiency factor)
  - avg_temp_f      : heat is the big confounder in Memphis — hotter => higher HR
                      at the same pace, so hot rides look LESS efficient.

Usage:
  python scripts/aerobic_efficiency.py                 # default: Memphis Road in Garmin_Data
  python scripts/aerobic_efficiency.py --match "Park City MTB" --folder "<dir>"
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import numpy as np
from fitparse import FitFile

HOME = Path.home()
DEFAULT_FOLDER = HOME / "DevProjects" / "Fitness Data" / "Garmin_Data"
MPS_TO_MPH = 2.2369363
LT1_HR = 138


def analyze_ride(path: Path) -> dict | None:
    ff = FitFile(str(path))
    session = {}
    for m in ff.get_messages("session"):
        session = {f.name: f.value for f in m}
        break

    recs = []
    prev = None
    for m in FitFile(str(path)).get_messages("record"):
        d = {f.name: f.value for f in m}
        ts = d.get("timestamp")
        dt = 1.0
        if prev is not None and ts is not None:
            dt = max(0.0, min((ts - prev).total_seconds(), 10.0))
        prev = ts
        spd = d.get("enhanced_speed") or d.get("speed")
        hr = d.get("heart_rate")
        if spd is None or hr is None:
            continue
        recs.append((dt, hr, spd * MPS_TO_MPH, d.get("temperature")))

    moving = [(dt, hr, mph, t) for (dt, hr, mph, t) in recs if mph > 3.0 and dt > 0]
    if not moving:
        return None

    tot_w = sum(dt for dt, *_ in moving)
    avg_speed = sum(mph * dt for dt, _, mph, _ in moving) / tot_w
    avg_hr = sum(hr * dt for dt, hr, _, _ in moving) / tot_w

    # band [130,140)
    band = [(dt, mph) for (dt, hr, mph, _) in moving if 130 <= hr < 140]
    band_w = sum(dt for dt, _ in band)
    band_speed = (sum(mph * dt for dt, mph in band) / band_w) if band_w > 0 else None

    # within-ride regression speed~HR over 125-145, predict at 135
    fit = [(hr, mph, dt) for (dt, hr, mph, _) in moving if 125 <= hr <= 145]
    fit_min = sum(dt for *_, dt in fit) / 60.0
    speed_at_135 = None
    if fit_min >= 10 and len({round(h) for h, *_ in fit}) >= 3:
        hrs = np.array([h for h, _, _ in fit], dtype=float)
        mph = np.array([s for _, s, _ in fit], dtype=float)
        wts = np.array([w for *_, w in fit], dtype=float)
        # weighted least squares, degree 1
        b, a = np.polyfit(hrs, mph, 1, w=wts)
        speed_at_135 = a + b * 135.0

    temps = [t for *_, t in recs if t is not None]
    temp_f = round(statistics.mean(temps) * 9 / 5 + 32) if temps else None

    dist_mi = (session.get("total_distance") or 0) * 0.000621371
    return {
        "file": path.name,
        "date": path.name[:10],
        "dist_mi": round(dist_mi, 1),
        "avg_hr": round(avg_hr, 1),
        "avg_speed": round(avg_speed, 1),
        "band_speed": round(band_speed, 2) if band_speed else None,
        "min_in_band": round(band_w / 60.0),
        "speed_at_135": round(speed_at_135, 2) if speed_at_135 else None,
        "ef": round(avg_speed / avg_hr * 100, 2),
        "temp_f": temp_f,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", default=str(DEFAULT_FOLDER))
    ap.add_argument("--match", default="Memphis Road")
    args = ap.parse_args()

    folder = Path(args.folder).expanduser()
    files = sorted(p for p in folder.glob(f"*{args.match}*.fit"))
    rows = [r for p in files if (r := analyze_ride(p))]
    rows.sort(key=lambda r: r["date"])

    hdr = f"{'date':<11}{'mi':>5}{'°F':>5}{'avgHR':>7}{'avgMPH':>8}{'mph@135':>9}{'band130-140':>13}{'min':>5}{'EF':>7}"
    print(f"\nAerobic-efficiency trend — match='{args.match}'  ({len(rows)} rides)\n")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        s135 = f"{r['speed_at_135']:.2f}" if r['speed_at_135'] else "  —"
        band = f"{r['band_speed']:.2f}" if r['band_speed'] else "  —"
        temp = f"{r['temp_f']}" if r['temp_f'] else "—"
        print(f"{r['date']:<11}{r['dist_mi']:>5}{temp:>5}{r['avg_hr']:>7}{r['avg_speed']:>8}{s135:>9}{band:>13}{r['min_in_band']:>5}{r['ef']:>7}")

    # period summaries on the headline metric (speed@135), valid rows only
    def period(label, pred):
        vals = [r["speed_at_135"] for r in rows if r["speed_at_135"] and pred(r["date"])]
        temps = [r["temp_f"] for r in rows if r["temp_f"] and pred(r["date"])]
        if vals:
            print(f"  {label:<22} mph@135 = {statistics.mean(vals):.2f}  "
                  f"(n={len(vals)}, avg {round(statistics.mean(temps))}°F)")

    print("\nPeriod means (headline = speed at a fixed 135 bpm):")
    period("2025 summer (Jul-Aug)", lambda d: d < "2025-12")
    period("2026 April", lambda d: d.startswith("2026-04"))
    period("2026 June", lambda d: d.startswith("2026-06"))

    # simple trend slope of speed@135 over time
    pts = [(r["date"], r["speed_at_135"]) for r in rows if r["speed_at_135"]]
    if len(pts) >= 3:
        from datetime import date
        x = np.array([date.fromisoformat(d).toordinal() for d, _ in pts], dtype=float)
        y = np.array([v for _, v in pts], dtype=float)
        slope = np.polyfit(x, y, 1)[0] * 30.0  # mph per ~month
        print(f"\nTrend: speed@135 changing {slope:+.2f} mph / month across the span "
              f"({pts[0][0]} → {pts[-1][0]}).")
    print()


if __name__ == "__main__":
    main()
