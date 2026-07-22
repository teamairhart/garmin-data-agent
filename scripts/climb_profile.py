#!/usr/bin/env python
"""Climb / grade / cadence / power deep-dive for MTB FIT files.

Usage:
    python scripts/climb_profile.py "<ride1.fit>" ["<ride2.fit>" ...] [--weight-kg 95] [--ftp 190]

Per ride: state breakdown (climb/descend/flat/coast/stopped), grade-bin table
(power/HR/cadence/speed by gradient), climb segmentation (every climb >=60 s and
>=15 m gain: power, W/kg, VAM, HR, cadence, development), short-vs-long climb
comparison, and punch count. With 2+ rides: matched-power climbing HR comparison
across days (fatigue read).

Assumes ~1 Hz records (Garmin smart recording off). Weight default 95 kg (Robert);
pass --weight-kg 79 for Jonathan.
"""
from __future__ import annotations

import argparse

import numpy as np
from fitparse import FitFile


def load(path: str) -> dict[str, np.ndarray]:
    recs = [{f.name: f.value for f in m} for m in FitFile(path).get_messages("record")]
    n = len(recs)

    def arr(*names, default=np.nan):
        out = np.full(n, default, float)
        for i, r in enumerate(recs):
            for nm in names:
                v = r.get(nm)
                if v is not None:
                    out[i] = float(v)
                    break
        return out

    return {
        "power": arr("power"),
        "hr": arr("heart_rate"),
        "cad": arr("cadence", default=0.0),
        "alt": arr("enhanced_altitude", "altitude"),
        "dist": arr("distance"),
        "speed": arr("enhanced_speed", "speed"),
    }


def smooth(x: np.ndarray, w: int) -> np.ndarray:
    x = np.copy(x)
    mask = np.isnan(x)
    if mask.any():
        idx = np.arange(len(x))
        x[mask] = np.interp(idx[mask], idx[~mask], x[~mask]) if (~mask).any() else 0.0
    k = np.ones(w) / w
    return np.convolve(x, k, mode="same")


def compute_grade(alt: np.ndarray, dist: np.ndarray, half_w: int = 8) -> np.ndarray:
    a = smooth(alt, 15)
    n = len(a)
    g = np.zeros(n)
    for i in range(n):
        lo, hi = max(0, i - half_w), min(n - 1, i + half_w)
        dd = dist[hi] - dist[lo]
        g[i] = 100.0 * (a[hi] - a[lo]) / dd if dd > 3 else 0.0
    return np.clip(g, -35, 35)


def close_gaps(mask: np.ndarray, gap_s: int) -> np.ndarray:
    out = mask.copy()
    i = 0
    n = len(mask)
    while i < n:
        if not out[i]:
            j = i
            while j < n and not out[j]:
                j += 1
            if 0 < i and j < n and (j - i) <= gap_s:
                out[i:j] = True
            i = j
        else:
            i += 1
    return out


def segments(mask: np.ndarray) -> list[tuple[int, int]]:
    segs, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            segs.append((i, j))
            i = j
        else:
            i += 1
    return segs


def np_power(p: np.ndarray) -> float:
    p = np.nan_to_num(p)
    if len(p) < 30:
        return float(np.mean(p))
    r = np.convolve(p, np.ones(30) / 30, mode="valid")
    return float(np.mean(r**4) ** 0.25)


def analyze(path: str, weight: float, ftp: float) -> dict:
    d = load(path)
    n = len(d["hr"])
    grade = compute_grade(d["alt"], d["dist"])
    moving = d["speed"] > 0.7
    coasting = moving & (d["cad"] < 20)
    climbing = moving & (grade >= 2.5)
    descending = moving & (grade <= -2.5)
    flat = moving & ~climbing & ~descending

    print(f"\n{'='*78}\n{path.split('/')[-1]}  ({n/3600:.2f} h, {np.nanmax(d['dist'])/1609.34:.1f} mi, "
          f"gain {max(0, float(np.nansum(np.clip(np.diff(smooth(d['alt'],15)),0,None))))*3.28084:,.0f} ft)\n{'='*78}")

    print("\n-- STATE BREAKDOWN --")
    for name, m in [("climbing (>=2.5%)", climbing), ("descending (<=-2.5%)", descending),
                    ("flat/rolling", flat), ("stopped", ~moving)]:
        if m.sum() == 0:
            continue
        pm = m & ~np.isnan(d["power"])
        print(f"  {name:22s} {m.sum()/60:6.1f} min ({m.sum()/n*100:4.1f}%)  "
              f"pwr {np.nanmean(d['power'][pm]) if pm.any() else 0:5.0f} W  "
              f"HR {np.nanmean(d['hr'][m]):5.0f}  cad {np.nanmean(d['cad'][m & (d['cad']>0)]) if (m & (d['cad']>0)).any() else 0:4.0f}  "
              f"spd {np.nanmean(d['speed'][m])*2.237:4.1f} mph")
    cd = coasting & descending
    print(f"  coasting overall       {coasting.sum()/60:6.1f} min ({coasting.sum()/max(1,moving.sum())*100:4.1f}% of moving; "
          f"{cd.sum()/max(1,descending.sum())*100:4.0f}% of descending time)")

    print("\n-- BY GRADE BIN (moving only) --")
    print(f"  {'grade':12s} {'time':>8s} {'%mv':>5s} {'pwr W':>6s} {'W/kg':>5s} {'HR':>4s} {'cad':>4s} {'mph':>5s}")
    bins = [(-35, -6, "steep down"), (-6, -2.5, "down"), (-2.5, 2.5, "flat-ish"),
            (2.5, 6, "moderate up"), (6, 9, "steep up"), (9, 35, "very steep")]
    for lo, hi, lbl in bins:
        m = moving & (grade >= lo) & (grade < hi)
        if m.sum() < 30:
            continue
        cadm = m & (d["cad"] > 0)
        print(f"  {lbl:12s} {m.sum()/60:6.1f}m {m.sum()/max(1,moving.sum())*100:5.1f} "
              f"{np.nanmean(d['power'][m]):6.0f} {np.nanmean(d['power'][m])/weight:5.2f} "
              f"{np.nanmean(d['hr'][m]):4.0f} {np.nanmean(d['cad'][cadm]) if cadm.any() else 0:4.0f} "
              f"{np.nanmean(d['speed'][m])*2.237:5.1f}")

    # climb segmentation
    cm = close_gaps(climbing, 45)
    climbs = []
    for a, b in segments(cm):
        dur = b - a
        gain = (smooth(d["alt"], 15)[b - 1] - smooth(d["alt"], 15)[a]) * 3.28084
        if dur >= 60 and gain >= 50:
            seg = slice(a, b)
            cadm = d["cad"][seg][d["cad"][seg] > 0]
            steep = (grade[seg] >= 6) & (d["cad"][seg] > 0)
            dev = (d["speed"][seg][steep] / (d["cad"][seg][steep] / 60.0)) if steep.any() else np.array([np.nan])
            climbs.append({
                "start_min": a / 60, "dur_min": dur / 60, "gain_ft": gain,
                "grade": float(np.nanmean(grade[seg])),
                "pwr": float(np.nanmean(d["power"][seg])), "np": np_power(d["power"][seg]),
                "hr0": float(np.nanmean(d["hr"][a:a + 30])), "hr1": float(np.nanmean(d["hr"][b - 30:b])),
                "hr": float(np.nanmean(d["hr"][seg])),
                "cad": float(np.mean(cadm)) if len(cadm) else np.nan,
                "vam": gain / 3.28084 / (dur / 3600.0),
                "dev_m": float(np.nanmedian(dev)),
            })
    print(f"\n-- CLIMBS (>=60 s, >=50 ft gain): {len(climbs)} --")
    print(f"  {'#':>2s} {'@min':>5s} {'dur':>5s} {'gain':>6s} {'grd%':>5s} {'avgW':>5s} {'W/kg':>5s} "
          f"{'HR':>4s} {'HR0->1':>8s} {'cad':>4s} {'VAM':>5s} {'dev_m':>5s}")
    for i, c in enumerate(climbs):
        print(f"  {i+1:2d} {c['start_min']:5.0f} {c['dur_min']:4.1f}m {c['gain_ft']:5.0f}f {c['grade']:5.1f} "
              f"{c['pwr']:5.0f} {c['pwr']/weight:5.2f} {c['hr']:4.0f} {c['hr0']:3.0f}->{c['hr1']:3.0f} "
              f"{c['cad']:4.0f} {c['vam']:5.0f} {c['dev_m']:5.1f}")

    for lbl, sel in [("short (1-3 min)", [c for c in climbs if c["dur_min"] < 3]),
                     ("medium (3-10 min)", [c for c in climbs if 3 <= c["dur_min"] < 10]),
                     ("long (>=10 min)", [c for c in climbs if c["dur_min"] >= 10])]:
        if sel:
            print(f"  {lbl:18s}: n={len(sel)}  avg {np.mean([c['pwr'] for c in sel]):.0f} W "
                  f"({np.mean([c['pwr'] for c in sel])/weight:.2f} W/kg)  HR {np.mean([c['hr'] for c in sel]):.0f}  "
                  f"cad {np.nanmean([c['cad'] for c in sel]):.0f}  VAM {np.mean([c['vam'] for c in sel]):.0f}")

    # punches: 15s+ over 1.3*ftp
    hard = np.nan_to_num(d["power"]) > 1.3 * ftp
    punches = [s for s in segments(hard) if (s[1] - s[0]) >= 15]
    print(f"  punches >= {1.3*ftp:.0f} W for 15 s+: {len(punches)}")

    return {"grade": grade, "climbing": climbing, "d": d, "climbs": climbs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fits", nargs="+")
    ap.add_argument("--weight-kg", type=float, default=95.0)
    ap.add_argument("--ftp", type=float, default=190.0)
    args = ap.parse_args()

    results = [analyze(f, args.weight_kg, args.ftp) for f in args.fits]

    if len(results) >= 2:
        print(f"\n{'='*78}\n-- CROSS-DAY: climbing HR at matched power (120-170 W) --")
        for f, r in zip(args.fits, results):
            m = r["climbing"] & (r["d"]["power"] >= 120) & (r["d"]["power"] <= 170)
            if m.sum() > 60:
                print(f"  {f.split('/')[-1]:45s} HR {np.nanmean(r['d']['hr'][m]):5.1f} "
                      f"(n={m.sum()/60:.0f} min, pwr {np.nanmean(r['d']['power'][m]):.0f} W)")


if __name__ == "__main__":
    main()
