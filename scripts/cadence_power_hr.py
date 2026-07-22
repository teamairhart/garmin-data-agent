#!/usr/bin/env python3
"""Cadence vs Power vs Gradient vs HR analysis for a single ride.

Isolates what actually drives HR by (a) HR-lag-correcting the trace, (b) a
multiple regression HR ~ power + cadence + grade so each factor is separated,
and (c) matched-power cadence bins — the cleanest test of "does spinning
faster cost HR at the *same* power?".

Built to answer the recurring cadence↔HR↔bounce question (see the 2026-06-30
and 2026-07-17 Ride_Analyses deep-dives). Re-run it on each new ride to keep
the cadence experiment going.

Usage:
    python scripts/cadence_power_hr.py "/path/to/ride.fit"
    python scripts/cadence_power_hr.py            # newest .fit in Garmin_Data
"""
import sys, glob, os
import numpy as np
from fitparse import FitFile

np.seterr(all="ignore")

GARMIN_DIR = os.path.expanduser("~/DevProjects/Fitness Data/Garmin_Data")


def latest_fit():
    fits = glob.glob(os.path.join(GARMIN_DIR, "*.fit"))
    if not fits:
        sys.exit(f"No .fit files in {GARMIN_DIR}")
    return max(fits, key=os.path.getmtime)


def load(path):
    f = FitFile(path)
    t, hr, cad, pwr, spd, alt, dist = [], [], [], [], [], [], []
    t0 = None
    for r in f.get_messages("record"):
        d = {x.name: x.value for x in r}
        ts = d.get("timestamp")
        if ts is None:
            continue
        if t0 is None:
            t0 = ts
        t.append((ts - t0).total_seconds())
        hr.append(d.get("heart_rate"))
        cad.append(d.get("cadence"))
        pwr.append(d.get("power"))
        spd.append(d.get("speed") if d.get("speed") is not None else d.get("enhanced_speed"))
        alt.append(d.get("altitude") if d.get("altitude") is not None else d.get("enhanced_altitude"))
        dist.append(d.get("distance"))

    def arr(x):
        return np.array([np.nan if v is None else float(v) for v in x])

    return (np.array(t, float), arr(hr), arr(cad), arr(pwr), arr(spd), arr(alt), arr(dist))


def smooth(x, w):
    x = x.copy()
    idx = np.arange(len(x))
    good = ~np.isnan(x)
    if good.sum() < 2:
        return x
    x = np.interp(idx, idx[good], x[good])
    return np.convolve(x, np.ones(w) / w, mode="same")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else latest_fit()
    print(f"Ride: {os.path.basename(path)}")
    t, hr, cad, pwr, spd, alt, dist = load(path)
    n = len(t)
    spd_mph = spd * 2.23694
    print(f"records: {n}, duration {t[-1]/60:.1f} min\n")

    # grade from smoothed altitude vs distance over ~20 s windows
    alt_s = smooth(alt, 15)
    win = 20
    grade = np.full(n, np.nan)
    for i in range(n):
        a = max(0, i - win // 2)
        b = min(n - 1, i + win // 2)
        dd = dist[b] - dist[a]
        if dd and dd > 3:
            grade[i] = (alt_s[b] - alt_s[a]) / dd * 100
    grade = np.clip(grade, -15, 15)
    print(f"GRADE: mean {np.nanmean(grade):+.2f}%, std {np.nanstd(grade):.2f}%")
    gv = grade[~np.isnan(grade)]
    for lo, hi, lab in [(-100, -2, "desc <-2%"), (-2, -0.5, "-2..-0.5"),
                        (-0.5, 0.5, "flat +/-0.5"), (0.5, 2, "0.5..2"), (2, 100, "climb >2%")]:
        m = (grade >= lo) & (grade < hi)
        print(f"  {lab:14s}: {100*np.sum(m)/len(gv):5.1f}%")

    # HR lag behind power (cross-correlation)
    def lagcorr(x, y, maxlag=60):
        best = (0, -9)
        xg, yg = x - np.nanmean(x), y - np.nanmean(y)
        for L in range(maxlag):
            a, b = xg[: n - L], yg[L:]
            m = ~np.isnan(a) & ~np.isnan(b)
            if m.sum() < 100:
                continue
            c = np.corrcoef(a[m], b[m])[0, 1]
            if c > best[1]:
                best = (L, c)
        return best

    lag, lc = lagcorr(pwr, hr)
    print(f"\nHR lag behind power: {lag}s (r={lc:.2f}) — HR shifted back {lag}s for matched analysis")
    hr_al = np.full(n, np.nan)
    hr_al[: n - lag] = hr[lag:]

    pwr_s = smooth(np.nan_to_num(pwr, nan=0.0), 20)
    cad_s = smooth(np.nan_to_num(cad, nan=0.0), 20)
    hr_s = smooth(hr_al, 20)
    mask = (cad > 5) & ~np.isnan(hr_s) & ~np.isnan(grade) & ~np.isnan(spd) & (spd_mph > 4)
    print(f"pedaling+moving samples: {mask.sum()} ({100*mask.sum()/n:.0f}% of ride)\n")

    # cadence distribution (pedaling only)
    peds = cad[cad > 5]
    print("CADENCE (pedaling): "
          f"avg {peds.mean():.0f} · median {np.median(peds):.0f} · "
          f">=85 {100*np.mean(peds>=85):.0f}% · >=90 {100*np.mean(peds>=90):.0f}% · "
          f"coasting {100*np.mean(cad<=5):.0f}%")

    # multiple regression HR ~ power + cadence + grade
    X = np.column_stack([np.ones(mask.sum()), pwr_s[mask], cad_s[mask], grade[mask]])
    Y = hr_s[mask]
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    pred = X @ beta
    r2 = 1 - np.sum((Y - pred) ** 2) / np.sum((Y - Y.mean()) ** 2)
    dof = len(Y) - X.shape[1]
    cov = (np.sum((Y - pred) ** 2) / dof) * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    print(f"\n=== Regression HR ~ power + cadence + grade  (R2={r2:.2f}, n={len(Y)}) ===")
    for nm, b, s in zip(["intercept", "power(W)", "cadence(rpm)", "grade(%)"], beta, se):
        print(f"  {nm:14s} coef {b:+7.3f}  SE {s:6.3f}  t={b/s:+6.1f}")
    print(f"  --> MATCHED power & grade: +10 rpm => {10*beta[2]:+.1f} bpm | +10 W => {10*beta[1]:+.1f} bpm")

    # matched-power cadence bins — the money test
    print("\n=== Matched-power windows: HR by cadence bin ===")
    for plo, phi in [(70, 110), (110, 150), (150, 240)]:
        pm = mask & (pwr_s >= plo) & (pwr_s < phi)
        if pm.sum() < 30:
            continue
        print(f"\n Power {plo}-{phi} W  (n={pm.sum()}, avg {pwr_s[pm].mean():.0f}W):")
        for clo, chi, lab in [(60, 80, "<80"), (80, 90, "80-90"), (90, 200, ">=90")]:
            cm = pm & (cad_s >= clo) & (cad_s < chi)
            if cm.sum() > 25:
                print(f"   cad {lab:6s} n={cm.sum():4d}: HR {hr_s[cm].mean():5.1f}  "
                      f"(power {pwr_s[cm].mean():5.0f}W, spd {spd_mph[cm].mean():4.1f}mph, "
                      f"grade {grade[cm].mean():+.2f}%)")

    h90 = mask & (cad_s >= 90)
    if h90.sum():
        print(f"\ncad>=90 time: {100*np.mean(hr_s[h90]>140):.0f}% had HR>140 "
              f"(avg power {pwr_s[h90].mean():.0f}W, avg cad {cad_s[h90].mean():.0f})")


if __name__ == "__main__":
    main()
