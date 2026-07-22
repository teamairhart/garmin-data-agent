#!/usr/bin/env python3
"""Per-ride fitness-marker extractor + persistent trend log.

The problem this solves: raw HR is confounded by altitude (~+2.5 bpm / 1,000 ft)
and heat, so "am I getting fitter?" can't be answered from a single ride. This
script parses the condition-controlled markers from each ride and APPENDS them to
a persistent CSV (data/ride_metrics.csv), so improvement can be tracked over time
with the confounders (altitude, temperature) sitting right next to the markers.

The garmin-ride-import skill calls this on every commit so the dataset is always
current and ready for a deep dive — whether or not we write a full analysis note.

Markers stored per ride (NaN when the input isn't present, e.g. HR-only rides):
  conditions : alt_median_ft, alt_gain_ft, temp_avg_f, temp_max_f
  fitness     : hr_at_120w, hr_at_150w  (matched-power median HR, HR-lag corrected)
                ef (NP/avgHR), decoupling_pct, adj_hr120 (altitude-adjusted, approx)
  load/shape  : np_w, avg_w, if_, tss, vi, avg_hr, max_hr, cad_avg, cad_pct_ge85
  zones       : pct_below_lt1, pct_aero_tempo, pct_threshold, pct_supra

Usage:
  python scripts/ride_metrics.py --fit "<ride>.fit"   # extract one ride, upsert CSV
  python scripts/ride_metrics.py --backfill           # (re)build CSV from all rides
  python scripts/ride_metrics.py --trend              # print improvement view
  python scripts/ride_metrics.py --fit "<ride>.fit" --trend   # both
"""
import argparse, csv, glob, os
import numpy as np
from fitparse import FitFile

np.seterr(all="ignore")

GARMIN_DIR = os.path.expanduser("~/DevProjects/Fitness Data/Garmin_Data")
CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "ride_metrics.csv")

# Testa lactate anchors (2026-03-18) — keep in sync with import_ride.py
LT1_HR, OBLA_HR, SUPRA_HR = 138, 156, 165
# Empirically measured from Jonathan's corpus (ride_metrics --trend, 2026-07):
# same power costs ~+2.5 bpm per 1,000 ft. Used only for the approximate
# altitude-adjusted marker so altitude rides are roughly comparable to sea level.
ALT_BPM_PER_1000FT = 2.5

FIELDS = [
    "date", "location", "type", "distance_mi", "duration_h",
    "alt_median_ft", "alt_gain_ft", "temp_avg_f", "temp_max_f",
    "avg_hr", "max_hr", "avg_w", "np_w", "if_", "tss", "vi", "ef",
    "hr_at_120w", "n_120", "hr_at_150w", "n_150", "adj_hr120", "decoupling_pct",
    "cad_avg", "cad_pct_ge85",
    "pct_below_lt1", "pct_aero_tempo", "pct_threshold", "pct_supra",
    "has_power", "file",
]


# ----------------------------- FIT loading -----------------------------------
def smooth(x, w):
    x = x.copy()
    idx = np.arange(len(x))
    good = ~np.isnan(x)
    if good.sum() < 2:
        return x
    x = np.interp(idx, idx[good], x[good])
    return np.convolve(x, np.ones(w) / w, mode="same")


def load(path):
    """Single pass over the FIT: record streams + the session summary message.

    NP/IF/TSS are taken from the session message (the Edge 840 computes them with
    its configured FTP), so they match what import_ride.py writes to the Training
    Log rather than being recomputed against a different FTP.
    """
    ff = FitFile(path)
    t, hr, cad, pwr, alt, tmp, dist = [], [], [], [], [], [], []
    session = {}
    t0 = None
    for msg in ff.get_messages():
        if msg.name == "session" and not session:
            session = {x.name: x.value for x in msg}
            continue
        if msg.name != "record":
            continue
        d = {x.name: x.value for x in msg}
        ts = d.get("timestamp")
        if ts is None:
            continue
        if t0 is None:
            t0 = ts
        t.append((ts - t0).total_seconds())
        hr.append(d.get("heart_rate"))
        cad.append(d.get("cadence"))
        pwr.append(d.get("power"))
        alt.append(d.get("altitude") if d.get("altitude") is not None else d.get("enhanced_altitude"))
        tmp.append(d.get("temperature"))
        dist.append(d.get("distance"))

    def a(x):
        return np.array([np.nan if v is None else float(v) for v in x])

    return np.array(t, float), a(hr), a(cad), a(pwr), a(alt), a(tmp), a(dist), session


def hr_lag(pwr, hr, n, maxlag=45):
    xg, yg = pwr - np.nanmean(pwr), hr - np.nanmean(hr)
    best = (0, -9.0)
    for L in range(maxlag):
        aa, bb = xg[: n - L], yg[L:]
        m = ~np.isnan(aa) & ~np.isnan(bb)
        if m.sum() < 100:
            continue
        c = np.corrcoef(aa[m], bb[m])[0, 1]
        if c > best[1]:
            best = (L, c)
    return best[0]


def parse_name(path):
    """'YYYY-MM-DD Location Type NNmi.fit' -> (date, location, type, distance)."""
    stem = os.path.basename(path)[:-4]
    p = stem.split(" ")
    date = p[0]
    dist_tok = p[-1] if p[-1].endswith("mi") else ""
    try:
        distance = float(dist_tok[:-2])
    except (ValueError, IndexError):
        distance = np.nan
    rtype = p[-2] if len(p) >= 3 and p[-2] in ("Road", "MTB", "Gravel") else "?"
    location = " ".join(p[1:-2]) if rtype != "?" else " ".join(p[1:-1])
    return date, location, rtype, distance


def band_median(hr_s, pwr_s, cad, lo, hi, start):
    m = (pwr_s >= lo) & (pwr_s < hi) & (cad > 5) & ~np.isnan(hr_s)
    m[:start] = False
    return (float(np.median(hr_s[m])), int(m.sum())) if m.sum() >= 60 else (np.nan, 0)


# --------------------------- metric computation ------------------------------
def compute_metrics(path):
    t, hr, cad, pwr, alt, tmp, dist, session = load(path)
    n = len(t)
    if n < 300:
        return None
    date, location, rtype, distance = parse_name(path)
    has_power = int(np.sum(~np.isnan(pwr)) >= 300)
    dur_h = round(t[-1] / 3600.0, 2) if n else np.nan

    # conditions
    alt_med = np.nanmedian(alt) * 3.281 if np.sum(~np.isnan(alt)) else np.nan
    alt_s = smooth(alt, 15) if np.sum(~np.isnan(alt)) else alt
    alt_gain = float(np.sum(np.clip(np.diff(alt_s), 0, None)) * 3.281) if np.sum(~np.isnan(alt)) else np.nan
    temp_avg = np.nanmedian(tmp) * 9 / 5 + 32 if np.sum(~np.isnan(tmp)) else np.nan
    temp_max = np.nanmax(tmp) * 9 / 5 + 32 if np.sum(~np.isnan(tmp)) else np.nan

    avg_hr = np.nanmean(hr[hr > 0]) if np.sum(hr > 0) else np.nan
    max_hr = np.nanmax(hr) if np.sum(~np.isnan(hr)) else np.nan

    # HR time-in-zone (Testa bands)
    hv = hr[~np.isnan(hr)]
    if len(hv):
        pct_below = 100 * np.mean(hv <= LT1_HR)
        pct_aero = 100 * np.mean((hv > LT1_HR) & (hv <= OBLA_HR))
        pct_thr = 100 * np.mean((hv > OBLA_HR) & (hv <= SUPRA_HR))
        pct_supra = 100 * np.mean(hv > SUPRA_HR)
    else:
        pct_below = pct_aero = pct_thr = pct_supra = np.nan

    # cadence (pedaling)
    peds = cad[cad > 5]
    cad_avg = np.mean(peds) if len(peds) else np.nan
    cad_ge85 = 100 * np.mean(peds >= 85) if len(peds) else np.nan

    # power-based markers
    avg_w = np_w = if_ = tss = vi = ef = hr120 = hr150 = adj = decoup = np.nan
    n120 = n150 = 0
    if has_power:
        p_fill = np.nan_to_num(pwr, nan=0.0)
        avg_w = session.get("avg_power")
        if avg_w is None:
            avg_w = np.nanmean(pwr[pwr > 0]) if np.sum(pwr > 0) else np.nan
        # NP/IF/TSS from the device session summary (matches import_ride.py / the Training Log);
        # fall back to a recomputed NP only if the head unit didn't record one.
        np_w = session.get("normalized_power")
        if np_w is None:
            roll = np.convolve(p_fill, np.ones(30) / 30, mode="same")
            np_w = float((np.mean(roll ** 4)) ** 0.25)
        if_ = session.get("intensity_factor")
        tss = session.get("training_stress_score")
        vi = np_w / avg_w if avg_w else np.nan
        if avg_hr and avg_hr > 0:
            ef = np_w / avg_hr

        lag = hr_lag(pwr, hr, n)
        hr_al = np.full(n, np.nan)
        hr_al[: n - lag] = hr[lag:]
        pwr_s = smooth(p_fill, 15)
        hr_s = smooth(hr_al, 15)
        start = min(480, n // 5)  # skip warm-up
        hr120, n120 = band_median(hr_s, pwr_s, cad, 110, 130, start)
        hr150, n150 = band_median(hr_s, pwr_s, cad, 140, 165, start)

        # decoupling: first vs second half efficiency (power/HR)
        half = n // 2
        def eff(s, e):
            pm = pwr[s:e]; hm = hr[s:e]
            ok = (pm > 0) & (hm > 0) & ~np.isnan(pm) & ~np.isnan(hm)
            return np.mean(pm[ok]) / np.mean(hm[ok]) if ok.sum() > 30 else np.nan
        e1, e2 = eff(0, half), eff(half, n)
        if e1 and not np.isnan(e1) and not np.isnan(e2):
            decoup = round((e2 - e1) / e1 * 100, 1)

    if not np.isnan(hr120) and not np.isnan(alt_med):
        adj = hr120 - ALT_BPM_PER_1000FT * (alt_med / 1000.0)

    def rnd(v, d=0):
        return "" if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), d)

    return {
        "date": date, "location": location, "type": rtype,
        "distance_mi": rnd(distance, 1), "duration_h": rnd(dur_h, 2),
        "alt_median_ft": rnd(alt_med), "alt_gain_ft": rnd(alt_gain),
        "temp_avg_f": rnd(temp_avg), "temp_max_f": rnd(temp_max),
        "avg_hr": rnd(avg_hr), "max_hr": rnd(max_hr),
        "avg_w": rnd(avg_w), "np_w": rnd(np_w), "if_": rnd(if_, 3),
        "tss": rnd(tss, 1), "vi": rnd(vi, 2), "ef": rnd(ef, 3),
        "hr_at_120w": rnd(hr120), "n_120": n120,
        "hr_at_150w": rnd(hr150), "n_150": n150,
        "adj_hr120": rnd(adj), "decoupling_pct": rnd(decoup, 1),
        "cad_avg": rnd(cad_avg), "cad_pct_ge85": rnd(cad_ge85),
        "pct_below_lt1": rnd(pct_below), "pct_aero_tempo": rnd(pct_aero),
        "pct_threshold": rnd(pct_thr), "pct_supra": rnd(pct_supra),
        "has_power": has_power, "file": os.path.basename(path),
    }


# ------------------------------- persistence ---------------------------------
def read_csv():
    if not os.path.exists(CSV_PATH):
        return {}
    with open(CSV_PATH, newline="") as f:
        return {r["file"]: r for r in csv.DictReader(f)}


def write_csv(rows_by_file):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    rows = sorted(rows_by_file.values(), key=lambda r: (r.get("date", ""), r.get("file", "")))
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def upsert(row):
    rows = read_csv()
    rows[row["file"]] = row
    write_csv(rows)


def backfill():
    rows = {}
    files = sorted(glob.glob(os.path.join(GARMIN_DIR, "*.fit")))
    for i, p in enumerate(files, 1):
        m = compute_metrics(p)
        if m:
            rows[m["file"]] = m
        print(f"  [{i}/{len(files)}] {os.path.basename(p)}")
    write_csv(rows)
    print(f"\nWrote {len(rows)} rides -> {CSV_PATH}")


# --------------------------------- trend -------------------------------------
def _f(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return np.nan


def trend():
    rows = list(read_csv().values())
    if not rows:
        print("No metrics yet — run --backfill first.")
        return
    rows.sort(key=lambda r: r["date"])
    withpwr = [r for r in rows if _f(r["hr_at_120w"]) == _f(r["hr_at_120w"])]  # not NaN
    sea = [r for r in withpwr if _f(r["alt_median_ft"]) < 1500]
    alti = [r for r in withpwr if _f(r["alt_median_ft"]) >= 4000]

    def show(group, label):
        if not group:
            return
        print(f"\n=== {label}  (HR at a fixed 120 W — lower = fitter) ===")
        print(f"{'date':11}{'loc':10}{'tempF':>6}{'altft':>7}{'HR@120W':>9}{'HR@150W':>9}{'EF':>6}{'decpl':>7}")
        for r in group[-12:]:
            print(f"{r['date']:11}{r['location'][:9]:10}{r['temp_avg_f']:>6}{r['alt_median_ft']:>7}"
                  f"{r['hr_at_120w']:>9}{r['hr_at_150w']:>9}{r['ef']:>6}{r['decoupling_pct']:>7}")
        # slope over time (bpm/month) — first vs last third
        H = np.array([_f(r["hr_at_120w"]) for r in group])
        if len(group) >= 6:
            k = max(2, len(group) // 3)
            early, late = np.nanmean(H[:k]), np.nanmean(H[-k:])
            print(f"  HR@120W: first {k} rides avg {early:.0f}  ->  last {k} rides avg {late:.0f}"
                  f"   ({late-early:+.0f} bpm)  [read WITH temp/altitude columns — not condition-controlled]")

    show(sea, "SEA LEVEL (Memphis)")
    show(alti, "ALTITUDE (Park City, >=4,000 ft)")

    # altitude-adjusted single trend across everything
    adj = [(r["date"], _f(r["adj_hr120"]), r["location"]) for r in withpwr if _f(r["adj_hr120"]) == _f(r["adj_hr120"])]
    if len(adj) >= 6:
        print("\n=== Altitude-adjusted HR@120W across ALL rides (approx, sea-level-equivalent) ===")
        A = np.array([a[1] for a in adj])
        k = max(2, len(adj) // 3)
        print(f"  first {k} avg {np.nanmean(A[:k]):.0f}  ->  last {k} avg {np.nanmean(A[-k:]):.0f}"
              f"   ({np.nanmean(A[-k:])-np.nanmean(A[:k]):+.0f} bpm)")
        print("  NOTE: adjusts altitude only (−2.5 bpm/1,000 ft); heat is NOT removed. A cool,")
        print("        rested, sea-level ride remains the gold-standard fitness check.")


def main():
    ap = argparse.ArgumentParser(description="Per-ride fitness-marker extractor + trend log")
    ap.add_argument("--fit", help="FIT file to extract and upsert into the trend CSV")
    ap.add_argument("--backfill", action="store_true", help="rebuild CSV from all rides in Garmin_Data")
    ap.add_argument("--trend", action="store_true", help="print the improvement view")
    args = ap.parse_args()

    if args.backfill:
        backfill()
    if args.fit:
        m = compute_metrics(args.fit)
        if not m:
            print(f"Could not parse {args.fit}")
        else:
            upsert(m)
            print(f"Logged {m['file']}: HR@120W={m['hr_at_120w']} EF={m['ef']} "
                  f"alt={m['alt_median_ft']}ft temp={m['temp_avg_f']}F -> {CSV_PATH}")
    if args.trend:
        trend()
    if not (args.backfill or args.fit or args.trend):
        ap.print_help()


if __name__ == "__main__":
    main()
