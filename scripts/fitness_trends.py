#!/usr/bin/env python3
"""Two-athlete, two-year fitness-trend corpus + board JSON builder.

Sweeps BOTH ride archives (Garmin_Data = Jonathan, Partner_Garmin = Robert) and
computes, per ride, everything ride_metrics.py stores PLUS the trend layers that
script doesn't cover:

  power curve : mean-max 5 s / 1 / 5 / 10 / 20 / 60 min (1 Hz grid, gaps = 0 W)
  ftp trail   : the head unit's configured threshold_power (session message)
  vo2 estimate: 10.8 x (best 5-min W / kg) + 7  (ACSM-style, per ride)

Per-ride corpus -> data/trend_corpus.csv (both athletes, idempotent by file).
Aggregates      -> data/fitness_trends.json (quarterly blocks + headline deltas)
                   shaped for the /board Fitness Trends section (push_trends.py).

Methodology notes (keep honest):
  - HR@120W etc reuse ride_metrics.py's exact smoothing/lag/band logic so numbers
    match the established CSV.
  - Robert's device TSS/IF are ignored (Fenix FTP setting is wrong for him); his
    zones use his own Testa anchors (LT1 118 / threshold 145).
  - Mean-max power is computed on a 1 Hz elapsed-time grid with recording gaps
    filled as 0 W — the conservative, TrainingPeaks-style convention.
  - MTB EF/decoupling are terrain-confounded; aggregates therefore separate
    road/sea-level from MTB/altitude and never mix the two in a trend line.
  - W/kg uses each athlete's CURRENT weight for all periods (historical weights
    not logged); flagged in the JSON as an assumption.
"""
import argparse, csv, glob, json, os, sys, warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore", message="Mean of empty slice")

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ride_metrics as rm  # reuse load/smooth/hr_lag/band_median/parse_name

np.seterr(all="ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_CSV = os.path.join(ROOT, "data", "trend_corpus.csv")
TRENDS_JSON = os.path.join(ROOT, "data", "fitness_trends.json")

ATHLETES = {
    "JA": {
        "dir": os.path.expanduser("~/DevProjects/Fitness Data/Garmin_Data"),
        "name": "Jonathan",
        "weight_kg": 90.6,
        "anchors": {"lt1_hr": 138, "lt2_hr": 156, "supra_hr": 165},
    },
    "RR": {
        "dir": os.path.expanduser("~/DevProjects/Fitness Data/Partner_Garmin"),
        "name": "Robert",
        "weight_kg": 95.0,
        "anchors": {"lt1_hr": 118, "lt2_hr": 145, "supra_hr": 153},
    },
}

MM_WINDOWS = {"p5s": 5, "p1m": 60, "p5m": 300, "p10m": 600, "p20m": 1200, "p60m": 3600}

FIELDS = [
    "athlete", "date", "location", "type", "distance_mi", "duration_h", "moving_h",
    "alt_median_ft", "alt_gain_ft", "temp_avg_f",
    "avg_hr", "max_hr", "hr_p995",
    "avg_w", "np_w", "kj", "vi", "ef", "device_ftp",
    "p5s", "p1m", "p5m", "p10m", "p20m", "p60m", "vo2_est",
    "hr_at_120w", "n_120", "hr_at_150w", "n_150", "decoupling_pct",
    "hrr60", "hrr_from", "hrr_n",
    "cad_avg", "cad_pct_ge85",
    "pct_below_lt1", "pct_aero_tempo", "pct_threshold", "pct_supra",
    "has_power", "file",
]


def mean_max(pwr_1hz, win):
    if len(pwr_1hz) < win:
        return np.nan
    c = np.cumsum(np.insert(pwr_1hz, 0, 0.0))
    return float(np.max((c[win:] - c[:-win]) / win))


def one_hz_power(t, pwr):
    """Resample to a 1 Hz elapsed grid; unrecorded seconds (pauses) count as 0 W."""
    dur = int(t[-1]) + 1
    grid = np.zeros(dur)
    idx = np.clip(t.astype(int), 0, dur - 1)
    ok = ~np.isnan(pwr)
    grid[idx[ok]] = pwr[ok]
    return grid


def _sec_grid(t, vals):
    """Values on a 1 s elapsed grid, NaN where no sample landed (pauses stay NaN)."""
    dur = int(t[-1]) + 1
    grid = np.full(dur, np.nan)
    idx = np.clip(t.astype(int), 0, dur - 1)
    ok = ~np.isnan(vals)
    grid[idx[ok]] = vals[ok]
    return grid


def hrr60(t, hr, pwr, cad, hard_hr, has_power, dist=None):
    """Best 60-s heart-rate recovery after a sustained hard effort.

    A window qualifies when: onset HR >= hard_hr (the athlete's threshold anchor)
    and the preceding 60 s averaged within 8 bpm of it (a sustained effort, not a
    spike); the following 60 s is genuine rest (power < 50 W; or cadence < 30 rpm
    on HR-only files; or, with no cadence stream either, a full stop — speed
    < 0.5 m/s from the distance channel) for >= 80% of samples; and the recording
    is contiguous (>= 90% HR coverage — auto-pause gaps disqualify, they hide the
    recovery). Returns (best_drop, onset_hr_of_best, n_events) — NaNs/0 when none.
    """
    if np.sum(~np.isnan(hr)) < 300:
        return np.nan, np.nan, 0
    hr_g = _sec_grid(t, hr)
    # bridge tiny (<=3 s) sensor dropouts so they don't fail the coverage check
    isn = np.isnan(hr_g)
    for i in np.where(isn)[0]:
        if i and not np.isnan(hr_g[i - 1]) and np.any(~np.isnan(hr_g[i:i + 4])):
            hr_g[i] = hr_g[i - 1]
    if has_power:
        rest = _sec_grid(t, pwr) < 50
    elif np.sum(~np.isnan(cad)) >= 300:
        rest = _sec_grid(t, cad) < 30
    elif dist is not None and np.sum(~np.isnan(dist)) >= 300:
        d_g = _sec_grid(t, dist)
        ok = ~np.isnan(d_g)
        d_g[ok] = np.maximum.accumulate(d_g[ok])  # distance is monotonic; guard noise
        spd = np.full(len(d_g), np.nan)
        spd[5:] = (d_g[5:] - d_g[:-5]) / 5.0
        rest = spd < 0.5
    else:
        return np.nan, np.nan, 0
    # NaN compares False throughout: no data never counts as resting
    dur = len(hr_g)
    best, best_from, onsets = np.nan, np.nan, []
    for i in range(60, dur - 63, 2):
        nxt, prv = hr_g[i:i + 61], hr_g[i - 60:i]
        if np.mean(~np.isnan(nxt)) < 0.9 or np.mean(~np.isnan(prv)) < 0.75:
            continue
        onset = np.nanmean(hr_g[max(0, i - 3):i + 3])
        if not onset >= hard_hr or not np.nanmean(prv) >= hard_hr - 8:
            continue
        if np.mean(rest[i:i + 61]) < 0.8:
            continue
        end = np.nanmean(hr_g[i + 57:i + 63])
        drop = onset - end
        if not (0 <= drop <= 80):
            continue
        onsets.append(i)
        if np.isnan(best) or drop > best:
            best, best_from = drop, onset
    n = 0
    last = -10**9
    for i in onsets:  # overlapping candidates of one recovery collapse to one event
        if i - last > 120:
            n += 1
        last = i
    return best, best_from, n


def compute(path, code):
    cfg = ATHLETES[code]
    t, hr, cad, pwr, alt, tmp, dist, session = rm.load(path)
    n = len(t)
    if n < 300:
        return None
    date, location, rtype, distance = rm.parse_name(path)
    has_power = int(np.sum(~np.isnan(pwr)) >= 300)
    a = cfg["anchors"]

    dur_h = round(t[-1] / 3600.0, 2)
    moving = np.sum((np.nan_to_num(pwr) > 10) | (np.nan_to_num(cad) > 5)) / 3600.0

    alt_med = np.nanmedian(alt) * 3.281 if np.sum(~np.isnan(alt)) else np.nan
    alt_s = rm.smooth(alt, 15) if np.sum(~np.isnan(alt)) else alt
    alt_gain = float(np.sum(np.clip(np.diff(alt_s), 0, None)) * 3.281) if np.sum(~np.isnan(alt)) else np.nan
    temp_avg = np.nanmedian(tmp) * 9 / 5 + 32 if np.sum(~np.isnan(tmp)) else np.nan

    hv = hr[~np.isnan(hr)]
    avg_hr = np.mean(hv[hv > 0]) if np.sum(hv > 0) else np.nan
    max_hr = np.max(hv) if len(hv) else np.nan
    hr_p995 = np.percentile(hv[hv > 0], 99.5) if np.sum(hv > 0) else np.nan

    if len(hv):
        pct_below = 100 * np.mean(hv <= a["lt1_hr"])
        pct_aero = 100 * np.mean((hv > a["lt1_hr"]) & (hv <= a["lt2_hr"]))
        pct_thr = 100 * np.mean((hv > a["lt2_hr"]) & (hv <= a["supra_hr"]))
        pct_supra = 100 * np.mean(hv > a["supra_hr"])
    else:
        pct_below = pct_aero = pct_thr = pct_supra = np.nan

    peds = cad[cad > 5]
    cad_avg = np.mean(peds) if len(peds) else np.nan
    cad_ge85 = 100 * np.mean(peds >= 85) if len(peds) else np.nan

    avg_w = np_w = kj = vi = ef = np.nan
    hr120 = hr150 = decoup = vo2 = np.nan
    n120 = n150 = 0
    mm = {k: np.nan for k in MM_WINDOWS}
    device_ftp = session.get("threshold_power") or np.nan

    if has_power:
        p1 = one_hz_power(t, pwr)
        for k, w in MM_WINDOWS.items():
            mm[k] = mean_max(p1, w)
        avg_w = session.get("avg_power") or (np.nanmean(pwr[pwr > 0]) if np.sum(pwr > 0) else np.nan)
        np_w = session.get("normalized_power")
        if np_w is None:
            roll = np.convolve(np.nan_to_num(pwr), np.ones(30) / 30, mode="same")
            np_w = float((np.mean(roll ** 4)) ** 0.25)
        kj = session.get("total_work")
        kj = kj / 1000.0 if kj else np.nan
        vi = np_w / avg_w if avg_w else np.nan
        if avg_hr and avg_hr > 0:
            ef = np_w / avg_hr
        if not np.isnan(mm["p5m"]):
            vo2 = 10.8 * (mm["p5m"] / cfg["weight_kg"]) + 7

        lag = rm.hr_lag(pwr, hr, n)
        hr_al = np.full(n, np.nan)
        hr_al[: n - lag] = hr[lag:]
        pwr_s = rm.smooth(np.nan_to_num(pwr), 15)
        hr_s = rm.smooth(hr_al, 15)
        start = min(480, n // 5)
        hr120, n120 = rm.band_median(hr_s, pwr_s, cad, 110, 130, start)
        hr150, n150 = rm.band_median(hr_s, pwr_s, cad, 140, 165, start)

        half = n // 2

        def eff(s, e):
            pm, hm = pwr[s:e], hr[s:e]
            ok = (pm > 0) & (hm > 0) & ~np.isnan(pm) & ~np.isnan(hm)
            return np.mean(pm[ok]) / np.mean(hm[ok]) if ok.sum() > 30 else np.nan

        e1, e2 = eff(0, half), eff(half, n)
        if e1 and not np.isnan(e1) and not np.isnan(e2):
            decoup = round((e2 - e1) / e1 * 100, 1)

    hrr, hrr_from, hrr_n = hrr60(t, hr, pwr, cad, a["lt2_hr"], has_power, dist=dist)

    def r(v, d=0):
        return "" if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), d)

    return {
        "athlete": code, "date": date, "location": location, "type": rtype,
        "distance_mi": r(distance, 1), "duration_h": r(dur_h, 2), "moving_h": r(moving, 2),
        "alt_median_ft": r(alt_med), "alt_gain_ft": r(alt_gain), "temp_avg_f": r(temp_avg),
        "avg_hr": r(avg_hr), "max_hr": r(max_hr), "hr_p995": r(hr_p995),
        "avg_w": r(avg_w), "np_w": r(np_w), "kj": r(kj), "vi": r(vi, 2), "ef": r(ef, 3),
        "device_ftp": r(device_ftp),
        "p5s": r(mm["p5s"]), "p1m": r(mm["p1m"]), "p5m": r(mm["p5m"]),
        "p10m": r(mm["p10m"]), "p20m": r(mm["p20m"]), "p60m": r(mm["p60m"]),
        "vo2_est": r(vo2, 1),
        "hr_at_120w": r(hr120), "n_120": n120, "hr_at_150w": r(hr150), "n_150": n150,
        "decoupling_pct": r(decoup, 1),
        "hrr60": r(hrr), "hrr_from": r(hrr_from), "hrr_n": hrr_n,
        "cad_avg": r(cad_avg), "cad_pct_ge85": r(cad_ge85),
        "pct_below_lt1": r(pct_below), "pct_aero_tempo": r(pct_aero),
        "pct_threshold": r(pct_thr), "pct_supra": r(pct_supra),
        "has_power": has_power, "file": os.path.basename(path),
    }


def sweep():
    rows = {}
    if os.path.exists(CORPUS_CSV):
        with open(CORPUS_CSV, newline="") as f:
            rows = {(x["athlete"], x["file"]): x for x in csv.DictReader(f)}
    for code, cfg in ATHLETES.items():
        files = sorted(glob.glob(os.path.join(cfg["dir"], "*.fit")))
        for i, p in enumerate(files, 1):
            key = (code, os.path.basename(p))
            # hrr_n is always numeric once computed — an empty value marks a row
            # from before the HRR column existed, so recompute to backfill it
            if key in rows and rows[key].get("hrr_n", "") != "":
                continue
            try:
                m = compute(p, code)
            except Exception as e:  # noqa: BLE001 — one bad file must not kill the sweep
                print(f"  [{code} {i}/{len(files)}] ERROR {os.path.basename(p)}: {e}")
                continue
            if m:
                rows[key] = m
            print(f"  [{code} {i}/{len(files)}] {os.path.basename(p)}")
    out = sorted(rows.values(), key=lambda x: (x["athlete"], x["date"], x["file"]))
    os.makedirs(os.path.dirname(CORPUS_CSV), exist_ok=True)
    with open(CORPUS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for x in out:
            w.writerow({k: x.get(k, "") for k in FIELDS})
    print(f"\nWrote {len(out)} rides -> {CORPUS_CSV}")


# ------------------------------ aggregation ---------------------------------
LAB_JSON = os.path.join(ROOT, "config", "lab_tests.json")

# RR 2026-08-02: raw max 196 / p99.5 186 vs next-best 179 and a lab curve topping
# at 153 @ 210 W — classic strap/wrist spike. Excluded from his max-HR trend.
HR_ARTIFACT_FILES = {
    ("RR", "2026-08-02 Park City Road 21mi.fit"),
    # 2026-07-25: single-sample 185 on an avg-122 Z2 day (p99.5 = 173); his
    # repeatable max is 179 — excluded from the max-HR trend, ride kept elsewhere.
    ("RR", "2026-07-25 Sun Valley MTB 28mi.fit"),
}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _isnum(v):
    return v == v and v != float("inf")  # not NaN


def _read_corpus():
    with open(CORPUS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _month(d):
    return d[:7]


def _best(rows, key):
    vals = [(_f(r[key]), r["date"]) for r in rows if _isnum(_f(r[key]))]
    return max(vals) if vals else (float("nan"), None)


def _series_monthly(rows, key, agg=max, min_n=1, pred=None):
    """[[YYYY-MM, value], ...] sorted, for sparklines."""
    by = {}
    for r in rows:
        if pred and not pred(r):
            continue
        v = _f(r[key])
        if _isnum(v):
            by.setdefault(_month(r["date"]), []).append(v)
    out = []
    for m in sorted(by):
        if len(by[m]) >= min_n:
            vals = by[m]
            out.append([m, round(agg(vals) if agg in (max, min) else float(np.median(vals)), 1)])
    return out


def _window(rows, lo, hi):
    return [r for r in rows if lo <= r["date"] < hi]


def _hrr_kpi(sub):
    """Recent-best HRR60 for the KPI tile: (value, onset_hr, date, prior_best, is_recent).

    Recent = the last 60 days of the athlete's corpus; prior_best = best before that
    window (NaN when the metric has no history yet). Returns None with no data at all.
    """
    q = [r for r in sub if _isnum(_f(r.get("hrr60"))) and _f(r.get("hrr_n")) > 0]
    if not q:
        return None
    latest = max(r["date"] for r in sub)
    cutoff = (datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
    recent = [r for r in q if r["date"] >= cutoff]
    pool = recent or q
    best = max(pool, key=lambda r: _f(r["hrr60"]))
    prior = [_f(r["hrr60"]) for r in q if r["date"] < cutoff]
    pbest = max(prior) if prior else float("nan")
    return _f(best["hrr60"]), _f(best["hrr_from"]), best["date"], pbest, bool(recent)


def _hrr_tile(sub):
    h = _hrr_kpi(sub)
    if not h:
        return None
    val, frm, dt, pbest, is_recent = h
    if not _isnum(pbest):
        delta, cls = "new metric — baseline set", "na"
    elif val >= pbest:
        delta, cls = f"ties/beats prior best {pbest:.0f}", "good"
    else:
        delta, cls = f"prior best {pbest:.0f}", "na"
    return {"label": "HRR (60 s)", "value": f"{val:.0f} bpm",
            "sub": f"from HR {frm:.0f} · {dt[5:]}" + ("" if is_recent else " (older ride)"),
            "delta": delta, "cls": cls}


def est_ftp(best20):
    return best20 * 0.95 if _isnum(best20) else float("nan")


def est_vo2_ftp(best20, kg):
    """MAP method: FTP ~= 0.95 x P20; MAP ~= FTP / 0.75; VO2max ~= 10.8 x MAP/kg + 7."""
    if not _isnum(best20):
        return float("nan")
    return 10.8 * (best20 * 0.95 / 0.75) / kg + 7


def aggregate():
    rows = _read_corpus()
    labs = {}
    if os.path.exists(LAB_JSON):
        with open(LAB_JSON) as f:
            labs = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    out = {"generated": datetime.now().strftime("%Y-%m-%d"), "athletes": {}}
    out["method_notes"] = [
        "Power curve = mean-max on a 1 Hz grid, recording gaps count as 0 W (TrainingPeaks convention).",
        "Est FTP = 0.95 x best 20-min (Coggan). Est VO2max = 10.8 x MAP/kg + 7 with MAP = FTP/0.75 (ACSM-style); where a true maximal 5-min exists, the 5-min method (10.8 x P5/kg + 7) is shown alongside.",
        "HR@120W = median HR in the 110-130 W band, HR-lag corrected, warm-up excluded (matches ride_metrics.csv). Confounders: ~+2.5 bpm/1,000 ft altitude, heat. Sea-level and altitude are never mixed in one trend.",
        "W/kg uses CURRENT weight for all periods (historical weights not logged).",
        "%truly-easy = share of ride time at/below each athlete's own LT1 heart rate (Testa anchors), the polarization KPI.",
        "HRR60 = biggest 60-s HR drop after a sustained hard effort (onset >= the athlete's threshold-HR anchor held >=60 s, then >=80% genuine rest — power <50 W, or no pedaling on HR-only files — with contiguous recording; auto-pause gaps disqualify and can hide recoveries). Faster = stronger parasympathetic rebound; compare only from similar onset HR — heat, altitude, and a lower starting HR all shrink the number.",
    ]

    for code, cfg in ATHLETES.items():
        sub = sorted([r for r in rows if r["athlete"] == code], key=lambda r: r["date"])
        if not sub:
            continue
        kg = cfg["weight_kg"]
        pw = [r for r in sub if r["has_power"] == "1"]
        clean_hr = [r for r in sub if (code, r["file"]) not in HR_ARTIFACT_FILES]

        a = {
            "name": cfg["name"],
            "weight_kg": kg,
            "n_rides": len(sub),
            "n_power": len(pw),
            "date_range": [sub[0]["date"], sub[-1]["date"]],
            "labs": labs.get(code, []),
        }

        # all-time + last-90-day power curves (value, date)
        curve = {}
        for k in MM_WINDOWS:
            v, d = _best(pw, k)
            v90, d90 = _best([r for r in pw if r["date"] >= "2026-05-15"], k)
            curve[k] = {
                "all": round(v) if _isnum(v) else None, "all_date": d,
                "r90": round(v90) if _isnum(v90) else None, "r90_date": d90,
                "all_wkg": round(v / kg, 2) if _isnum(v) else None,
            }
        a["curve"] = curve

        # sparkline series
        a["spark"] = {
            "p20m": _series_monthly(pw, "p20m", agg=max),
            "hours": _series_monthly(sub, "duration_h", agg=sum),
            "easy": _series_monthly(sub, "pct_below_lt1", agg="med"),
            "hr120_sea": _series_monthly(
                pw, "hr_at_120w", agg="med",
                pred=lambda r: _isnum(_f(r["alt_median_ft"])) and _f(r["alt_median_ft"]) < 1500 and _f(r["n_120"]) >= 60),
            "hr120_alt": _series_monthly(
                pw, "hr_at_120w", agg="med",
                pred=lambda r: _isnum(_f(r["alt_median_ft"])) and _f(r["alt_median_ft"]) >= 4000 and _f(r["n_120"]) >= 60),
        }
        # fix sum aggregation emitted via _series_monthly(max) path
        a["spark"]["hours"] = []
        by = {}
        for r in sub:
            v = _f(r["duration_h"])
            if _isnum(v):
                by.setdefault(_month(r["date"]), 0.0)
                by[_month(r["date"])] += v
        a["spark"]["hours"] = [[m, round(by[m], 1)] for m in sorted(by)]

        out["athletes"][code] = a

    # ---------------- Jonathan: YoY same-window deltas ----------------
    ja = out["athletes"].get("JA")
    if ja:
        sub = sorted([r for r in rows if r["athlete"] == "JA"], key=lambda r: r["date"])
        pw = [r for r in sub if r["has_power"] == "1"]
        kg = ATHLETES["JA"]["weight_kg"]
        w25 = _window(sub, "2025-07-01", "2025-08-14")
        w26 = _window(sub, "2026-07-01", "2026-08-14")
        p25, p26 = [r for r in w25 if r["has_power"] == "1"], [r for r in w26 if r["has_power"] == "1"]
        b20_25, _ = _best(p25, "p20m")
        b20_26, _ = _best(p26, "p20m")
        b5_25, _ = _best(p25, "p5m")
        easy25 = float(np.nanmean([_f(r["pct_below_lt1"]) for r in w25]))
        easy26 = float(np.nanmean([_f(r["pct_below_lt1"]) for r in w26]))
        hrs25 = float(np.nansum([_f(r["duration_h"]) for r in w25]))
        hrs26 = float(np.nansum([_f(r["duration_h"]) for r in w26]))
        maxhr25 = float(np.nanmax([_f(r["hr_p995"]) for r in _window(sub, "2025-07-01", "2026-01-01")]))
        sea = [r for r in pw if _isnum(_f(r["alt_median_ft"])) and _f(r["alt_median_ft"]) < 1500 and _f(r["n_120"]) >= 60]
        sea26 = [(_f(r["hr_at_120w"]), r["date"], _f(r["temp_avg_f"])) for r in sea if r["date"] >= "2026-06-01"]
        best_sea = min(sea26) if sea26 else (float("nan"), None, None)

        ja["deltas"] = [
            {"metric": "Lab lactate curve (Testa)", "then": "LT1 130 W - OBLA 210 W", "then_label": "Jul 7 2025 (88.6 kg)",
             "now": "LT1 190 W - OBLA 240 W", "now_label": "Mar 16 2026",
             "delta": "LT1 +46% - OBLA +14%", "dir": "up", "good": True,
             "note": "The whole curve shifted right: 2-mMol lactate used to arrive at 165 W, now at 205 W. The gain landed exactly where the diagnosis pointed — the aerobic base — and the lab pair brackets the field data (lab OBLA 210 vs field est FTP 216 in 2025; 240 vs 237-238 in 2026)."},
            {"metric": "Best 20-min power", "then": f"{b20_25:.0f} W", "then_label": "Jul-Aug 2025",
             "now": f"{b20_26:.0f} W", "now_label": "Jul 2026 (FTP test)",
             "delta": f"+{b20_26-b20_25:.0f} W (+{100*(b20_26-b20_25)/b20_25:.0f}%)", "dir": "up", "good": True,
             "note": "Like-for-like mean-max from ride files, same summer window."},
            {"metric": "Est. FTP (0.95 x 20-min)", "then": f"{est_ftp(b20_25):.0f} W ({est_ftp(b20_25)/kg:.2f} W/kg)",
             "then_label": "Jul-Aug 2025", "now": f"{est_ftp(b20_26):.0f} W ({est_ftp(b20_26)/kg:.2f} W/kg)",
             "now_label": "Jul 2026", "delta": f"+{est_ftp(b20_26)-est_ftp(b20_25):.0f} W", "dir": "up", "good": True,
             "note": "Rounds to the tested hot-floor FTP 237 W (Jul 30) and sits just under the Mar-2026 lab OBLA 240 W. Coggan bands @ 90.6 kg: 2.62 W/kg = upper 'fair', Cat-4/5 door; 195 lb goal makes the same watts 2.68."},
            {"metric": "Est. VO2max (MAP method)", "then": f"~{est_vo2_ftp(b20_25, kg):.0f}", "then_label": "2025",
             "now": f"~{est_vo2_ftp(b20_26, kg):.0f} ml/kg/min", "now_label": "2026",
             "delta": f"+{est_vo2_ftp(b20_26, kg)-est_vo2_ftp(b20_25, kg):.0f}", "dir": "up", "good": True,
             "note": "Age-graded (men 45-49): ~45 = 'good', excellent starts ~48. Lab VO2 never directly measured."},
            {"metric": "Verified max HR", "then": f"{maxhr25:.0f} bpm", "then_label": "2025 observed",
             "now": "194 bpm", "now_label": "Jul 2026 FTP test",
             "delta": "+8 observed", "dir": "flat", "good": None,
             "note": "An anchor, not a fitness gain — the 2026 test simply reached a true max. Zones re-based off 194."},
            {"metric": "HR @ 120 W (sea level)", "then": "no 2025 baseline", "then_label": "Garmin stayed home",
             "now": f"{best_sea[0]:.0f} bpm best / 133-137 typical", "now_label": "Jun-Aug 2026",
             "delta": "-8 bpm within 2026", "dir": "up", "good": True,
             "note": "149 post-test spike (Jul 28) -> 129 all-time best (Aug 1). Cool-morning October retest is the gold standard."},
            {"metric": "HR @ 120 W (altitude, matched climb)", "then": "2025-07-02 Armstrong-Pinecone", "then_label": "",
             "now": "2026-07-24 same climb", "now_label": "",
             "delta": "-4 bpm at matched power", "dir": "up", "good": True,
             "note": "Same-climb YoY control (see 7/24 analysis): fitter engine at identical watts, plus -13 W pedaling avg from smarter pacing."},
            {"metric": "Truly-easy discipline (% time <= LT1)", "then": f"{easy25:.0f}%", "then_label": "Jul-Aug 2025",
             "now": f"{easy26:.0f}%", "now_label": "Jul-Aug 2026",
             "delta": f"+{easy26-easy25:.0f} pts", "dir": "up", "good": True,
             "note": "Testa's #1 fix. 2025 was grey-zone riding (78% above LT1 across the old corpus); the polarized split is taking hold."},
            {"metric": "Durability at race scale", "then": "P2P 2025: 12:03, hour-7 bonk", "then_label": "",
             "now": "2026: 9.6 h recon, no bonk; ~21-h-fasted TSS-373 day", "now_label": "",
             "delta": "shared course span ridden 14 min faster than race pace, in training", "dir": "up", "good": True,
             "note": "Hour-6-7 climbing at 188 W @ HR 160 on the exact 2025 bonk terrain; matched-power HR improved through the day."},
            {"metric": "Volume (Jul 1 - Aug 13)", "then": f"{hrs25:.0f} h", "then_label": "2025",
             "now": f"{hrs26:.0f} h", "now_label": "2026",
             "delta": "flat by design", "dir": "flat", "good": None,
             "note": "Same hours, different composition: 2026 adds structure, fuel protocol, and the biggest single days of the log."},
            {"metric": "Top-end (5-min / sprint)", "then": f"{b5_25:.0f} W 5-min (2025)", "then_label": "",
             "now": "253 W 5-min in-test; 1,144 W 5-s (Nov 2025)", "now_label": "",
             "delta": "deliberately untested in 2026", "dir": "flat", "good": None,
             "note": "The phenotype is anaerobic-dominant (Strava 8-wk 5-min 349 W, Mar 2026); 2026 training targets the aerobic limiter instead."},
        ]

        ja["kpis"] = [
            {"label": "Est. FTP", "value": f"{est_ftp(b20_26):.0f} W", "sub": f"{est_ftp(b20_26)/kg:.2f} W/kg",
             "delta": f"+{est_ftp(b20_26)-est_ftp(b20_25):.0f} W YoY", "cls": "good"},
            {"label": "Est. VO2max", "value": f"~{est_vo2_ftp(b20_26, kg):.0f}", "sub": "ml/kg/min · 'good' 45-49",
             "delta": f"+{est_vo2_ftp(b20_26, kg)-est_vo2_ftp(b20_25, kg):.0f} YoY", "cls": "good"},
            {"label": "Best 20-min", "value": f"{b20_26:.0f} W", "sub": "Jul 30 test",
             "delta": f"+{b20_26-b20_25:.0f} W YoY", "cls": "good"},
            {"label": "Max HR", "value": "194", "sub": "verified Jul 2026",
             "delta": "zones re-based", "cls": "na"},
        ]
        t = _hrr_tile(sub)
        if t:
            ja["kpis"].append(t)

    # ---------------- Robert: era-over-era deltas ----------------
    rr = out["athletes"].get("RR")
    if rr:
        sub = sorted([r for r in rows if r["athlete"] == "RR"], key=lambda r: r["date"])
        kg = ATHLETES["RR"]["weight_kg"]
        pw = [r for r in sub if r["has_power"] == "1"]
        b20, b20d = _best(pw, "p20m")
        b60, _ = _best(pw, "p60m")
        b5, _ = _best(pw, "p5m")
        q2 = _window(sub, "2026-04-01", "2026-07-01")
        q3 = _window(sub, "2026-07-01", "2026-10-01")
        easy2 = float(np.nanmean([_f(r["pct_below_lt1"]) for r in q2]))
        easy3 = float(np.nanmean([_f(r["pct_below_lt1"]) for r in q3]))
        clean = [r for r in sub if ("RR", r["file"]) not in HR_ARTIFACT_FILES]
        maxhr = float(np.nanmax([_f(r["max_hr"]) for r in clean]))

        rr["deltas"] = [
            {"metric": "FTP", "then": "190 W lab (2.0 W/kg)", "then_label": "Testa, Dec 2025",
             "now": "230 W field test (2.42 W/kg)", "now_label": f"Jul 23 2026 · 20:01 @ {b20:.0f} W",
             "delta": "+21%", "dir": "up", "good": True,
             "note": f"The Coggan estimate off the test (0.95 x {b20:.0f} = {est_ftp(b20):.0f}) converges on the tested 230. Corroborated Aug 8: {b60:.0f} W steady for a full hour below threshold HR."},
            {"metric": "Est. VO2max", "then": "33.4 ml/kg/min (lab)", "then_label": "Dec 2025",
             "now": f"~{10.8*b5/kg+7:.0f}-{est_vo2_ftp(b20, kg):.0f} field est", "now_label": "Jul-Aug 2026",
             "delta": "+3-8", "dir": "up", "good": True,
             "note": "5-min method gives the floor, FTP/MAP method the ceiling. Age-graded (men 60-64): 33 was 'above average', 36-41 'good', 41+ 'excellent' — at least one band up at 60, possibly two. A lab retest would pin it."},
            {"metric": "Power benchmarks (first power meter)", "then": "none — HR-only era", "then_label": "through Jul 15",
             "now": f"5-min {b5:.0f} W - 20-min {b20:.0f} W - 60-min {b60:.0f} W", "now_label": "since Jul 19",
             "delta": "baseline set", "dir": "flat", "good": None,
             "note": "Assioma pedals arrived Jul 19; the Jul 23 FTP test + three more rides were recovered from board uploads into the archive on Aug 13, so this power curve is now complete. The 2027 comparison starts here."},
            {"metric": "Truly-easy discipline (% time <= LT1 118)", "then": f"{easy2:.0f}%", "then_label": "Q2 2026",
             "now": f"{easy3:.0f}%", "now_label": "Q3 2026",
             "delta": f"+{easy3-easy2:.0f} pts", "dir": "up", "good": True,
             "note": "His LT1 (100 W / 118 bpm) is the limiter Testa flagged — easy volume is exactly the prescription."},
            {"metric": "Durability (the superpower)", "then": "Leadville recon: 7.5 h @ 12k ft, ZERO drift", "then_label": "May 2026",
             "now": "P2P recons: 9.6 h, drift ~0 again", "now_label": "Jul-Aug 2026",
             "delta": "elite marker, repeatedly confirmed", "dir": "up", "good": True,
             "note": "Friel standard: <5% Pw:HR decoupling = aerobically durable. He posts ~0 on 8-10 h days. Pacing/durability is NOT his limiter — W/kg is."},
            {"metric": "Observed max HR", "then": "—", "then_label": "",
             "now": f"{maxhr:.0f} bpm (clean)", "now_label": "May 2026",
             "delta": "", "dir": "flat", "good": None,
             "note": "An Aug 2 spike to 196 was a strap artifact (next-best 179; lab curve tops at 153 @ 210 W). Compressed zones (LT1 118 - threshold 145) make HR pacing knife-edge; power fixes that."},
            {"metric": "The mission", "then": "95 kg, 2.0 W/kg", "then_label": "Dec 2025",
             "now": "climbing races reward W/kg", "now_label": "",
             "delta": "body comp = highest-leverage lever", "dir": "flat", "good": None,
             "note": "Every kg is ~5 m/h VAM (~3-4 min across P2P's climbing). The engine is proven durable; make it lighter."},
        ]

        rr["kpis"] = [
            {"label": "FTP", "value": "230 W", "sub": "2.42 W/kg · tested Jul 23",
             "delta": "+21% vs Dec lab", "cls": "good"},
            {"label": "Est. VO2max", "value": f"{10.8*b5/kg+7:.0f}-{est_vo2_ftp(b20, kg):.0f}", "sub": "lab 33.4 Dec 2025",
             "delta": "1-2 bands up at 60", "cls": "good"},
            {"label": "Best 20-min", "value": f"{b20:.0f} W", "sub": f"{b20/kg:.2f} W/kg · FTP test",
             "delta": "tested, not estimated", "cls": "good"},
            {"label": "Max HR (clean)", "value": f"{maxhr:.0f}", "sub": "repeatable · May 2026",
             "delta": "2 spike artifacts excluded", "cls": "na"},
        ]
        t = _hrr_tile(sub)
        if t:
            rr["kpis"].append(t)

    with open(TRENDS_JSON, "w") as f:
        json.dump(out, f, indent=1)
    print(f"Wrote {TRENDS_JSON}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true", help="(re)build the two-athlete corpus CSV (incremental)")
    ap.add_argument("--force", action="store_true", help="ignore existing corpus rows, recompute everything")
    ap.add_argument("--aggregate", action="store_true", help="build data/fitness_trends.json from the corpus")
    args = ap.parse_args()
    if args.force and os.path.exists(CORPUS_CSV):
        os.remove(CORPUS_CSV)
    if args.sweep or args.force:
        sweep()
    if args.aggregate:
        aggregate()
    if not (args.sweep or args.force or args.aggregate):
        ap.print_help()


if __name__ == "__main__":
    main()
