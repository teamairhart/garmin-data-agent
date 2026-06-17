#!/usr/bin/env python3
"""Import Garmin ride zips from Downloads into the ride-data folders.

This is the deterministic engine behind the `garmin-ride-import` skill. It does
all the mechanical, repeatable work and emits JSON; the *judgment* (confirming an
ambiguous location, deciding whether a ride warrants a deep-dive, writing the
Training Log prose) is left to the skill (Claude).

Two subcommands:

  scan    Read-only. Find candidate zips in Downloads, parse each ride, and print
          a JSON report: proposed filename, target folder, full ride stats
          (distance, ascent, HR zones vs the Testa anchors, HR drift, temperature,
          power/TSS/decoupling when present), collision/duplicate status, owner
          guess, and a "notable" suggestion. Touches nothing.

  commit  Execute a plan (JSON on stdin or --plan FILE) the skill produced after
          applying judgment. For each ride: re-extract + validate the FIT, copy it
          into the target folder under its final name, append a row to that
          folder's _rename_map.csv, and delete the original zip. Prints JSON of
          what it did. Refuses to overwrite a differing file.

Anchors (Dr. Max Testa lactate test, 2026-03-18): LT1 138 bpm / 190 W,
OBLA 156 bpm / 240 W. HR bands used for time-in-zone:
  below_lt1 (<=138, "true Z2") | aero_tempo (139-156) | threshold (157-165) | supra (>165)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from fitparse import FitFile

# ---- constants -------------------------------------------------------------

HOME = Path.home()
DOWNLOADS = HOME / "Downloads"
DATA_ROOT = HOME / "DevProjects" / "Fitness Data"
FOLDER_JONATHAN = DATA_ROOT / "Garmin_Data"
FOLDER_PARTNER = DATA_ROOT / "Partner_Garmin"

FIT_MAGIC = b".FIT"
SEMICIRCLE_TO_DEGREES = 180.0 / 2**31
M_TO_MI = 0.000621371
M_TO_FT = 3.28084

# Testa anchors
LT1_HR = 138
OBLA_HR = 156
SUPRA_HR = 165  # practical "over threshold" line used in the Training Log

# Garmin product id for Jonathan's head unit (Edge 840). Routes to Garmin_Data.
EDGE_840_PRODUCT = 4062

# Coarse start-location boxes -> base location label. Anything outside these is
# flagged for the skill to confirm/label (e.g. travel rides, new trailheads).
REGION_BOXES = [
    # (label, lat_min, lat_max, lon_min, lon_max)
    ("Park City", 39.5, 41.5, -112.5, -110.0),
    ("Memphis", 34.0, 36.5, -91.5, -89.0),
    ("St George", 36.8, 37.4, -113.9, -113.2),
    ("Leadville", 39.0, 39.5, -106.6, -106.0),
    ("Sanibel", 26.2, 26.7, -82.3, -81.8),
]

# sub_sport / sport -> filename Type token
TYPE_MAP = {
    "road": "Road",
    "mountain": "MTB",
    "gravel_cycling": "Gravel",
    "gravel": "Gravel",
    "cyclocross": "CX",
}


# ---- FIT discovery / validation -------------------------------------------

def is_fit_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            header = fh.read(12)
        return len(header) >= 12 and header[8:12] == FIT_MAGIC
    except OSError:
        return False


def zip_has_fit(zip_path: Path) -> bool:
    """Cheap peek: does this archive plausibly contain Garmin FIT data?"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                low = name.lower()
                if low.endswith(".fit") or low.endswith(".fit.gz") or "di_connect" in low:
                    return True
    except (zipfile.BadZipFile, OSError):
        return False
    return False


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_fits(zip_path: Path, workdir: Path) -> list[Path]:
    """Recursively unpack a zip (incl. nested zip/gz) and return valid .fit paths."""
    fits: list[Path] = []
    seen: set[str] = set()

    def walk(src: Path) -> None:
        if src.is_dir():
            for child in sorted(src.rglob("*")):
                if child.is_file():
                    handle(child)
        elif src.is_file():
            handle(src)

    def handle(p: Path) -> None:
        low = p.name.lower()
        if low.endswith(".fit"):
            if is_fit_file(p):
                digest = sha1(p)
                if digest not in seen:
                    seen.add(digest)
                    fits.append(p)
        elif low.endswith(".zip"):
            sub = Path(tempfile.mkdtemp(dir=workdir, prefix="zip_"))
            try:
                with zipfile.ZipFile(p) as zf:
                    zf.extractall(sub)
                walk(sub)
            except (zipfile.BadZipFile, OSError):
                pass
        elif low.endswith(".gz"):
            out_name = p.name[:-3]
            if not out_name.lower().endswith(".fit"):
                out_name += ".fit"
            out = Path(tempfile.mkdtemp(dir=workdir, prefix="gz_")) / out_name
            try:
                with gzip.open(p, "rb") as s, out.open("wb") as d:
                    shutil.copyfileobj(s, d)
                handle(out)
            except OSError:
                pass

    walk(zip_path)
    return fits


# ---- FIT parsing / stats ---------------------------------------------------

def _semis(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v) * SEMICIRCLE_TO_DEGREES
    except (TypeError, ValueError):
        return None


def _first_msg(ff: FitFile, name: str) -> dict[str, Any]:
    for m in ff.get_messages(name):
        return {fld.name: fld.value for fld in m}
    return {}


def classify_region(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    if lat is None or lon is None:
        return None
    for label, la0, la1, lo0, lo1 in REGION_BOXES:
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            return label
    return None


def classify_type(session: dict[str, Any]) -> Optional[str]:
    sub = (session.get("sub_sport") or "")
    sport = (session.get("sport") or "")
    if isinstance(sub, str) and sub.lower() in TYPE_MAP:
        return TYPE_MAP[sub.lower()]
    if isinstance(sport, str) and sport.lower() in TYPE_MAP:
        return TYPE_MAP[sport.lower()]
    return None


def _weighted(pairs: list[tuple[float, float]]) -> Optional[float]:
    """pairs: list of (value, weight). Returns weighted mean or None."""
    num = sum(v * w for v, w in pairs)
    den = sum(w for _, w in pairs)
    return num / den if den > 0 else None


@dataclass
class RideStats:
    data: dict[str, Any] = field(default_factory=dict)


def parse_ride(fit_path: Path) -> dict[str, Any]:
    ff = FitFile(str(fit_path))
    session = _first_msg(ff, "session")
    activity = _first_msg(FitFile(str(fit_path)), "activity")
    file_id = _first_msg(FitFile(str(fit_path)), "file_id")

    # ---- local date from activity local_timestamp vs UTC timestamp ----
    utc_start = session.get("start_time")
    local_offset_known = False
    date_local = None
    if activity.get("local_timestamp") and activity.get("timestamp"):
        try:
            offset = activity["local_timestamp"] - activity["timestamp"]
            if utc_start is not None:
                date_local = (utc_start + offset).date().isoformat()
                local_offset_known = True
        except Exception:
            pass
    if date_local is None and utc_start is not None:
        date_local = utc_start.date().isoformat()

    lat = _semis(session.get("start_position_lat"))
    lon = _semis(session.get("start_position_long"))
    region = classify_region(lat, lon)
    type_label = classify_type(session)

    dist_m = session.get("total_distance") or 0.0
    dist_mi = dist_m * M_TO_MI
    asc_ft = (session.get("total_ascent") or 0.0) * M_TO_FT
    timer_s = session.get("total_timer_time") or 0.0
    dur_h = timer_s / 3600.0
    avg_speed_mps = session.get("enhanced_avg_speed") or session.get("avg_speed")
    moving_mph = (avg_speed_mps * 2.2369363) if avg_speed_mps else (
        (dist_mi / dur_h) if dur_h > 0 else None
    )

    avg_power = session.get("avg_power")
    np_power = session.get("normalized_power")
    has_power = bool(avg_power) or bool(np_power)

    # ---- record-level pass: HR zones, drift, temperature, decoupling ----
    records: list[dict[str, Any]] = []
    prev_ts = None
    for m in FitFile(str(fit_path)).get_messages("record"):
        d = {fld.name: fld.value for fld in m}
        ts = d.get("timestamp")
        dt = 1.0
        if prev_ts is not None and ts is not None:
            dt = (ts - prev_ts).total_seconds()
            dt = max(0.0, min(dt, 10.0))
        prev_ts = ts
        d["_dt"] = dt
        records.append(d)

    hr_pairs = [(float(r["heart_rate"]), r["_dt"]) for r in records
                if r.get("heart_rate") is not None and r["_dt"] > 0]
    total_w = sum(w for _, w in hr_pairs)

    def band_pct(lo: Optional[int], hi: Optional[int]) -> Optional[float]:
        if total_w <= 0:
            return None
        s = sum(w for v, w in hr_pairs
                if (lo is None or v > lo) and (hi is None or v <= hi))
        return round(100.0 * s / total_w, 1)

    hr_zones = {
        "below_lt1_pct": band_pct(None, LT1_HR),       # <=138
        "aero_tempo_pct": band_pct(LT1_HR, OBLA_HR),    # 139-156
        "threshold_pct": band_pct(OBLA_HR, SUPRA_HR),   # 157-165
        "supra_pct": band_pct(SUPRA_HR, None),          # >165
    } if hr_pairs else None

    # HR drift: split moving time in half, compare weighted-avg HR each half.
    hr_drift = None
    if hr_pairs and total_w > 0:
        half = total_w / 2.0
        cum = 0.0
        first, second = [], []
        for v, w in hr_pairs:
            if cum < half:
                first.append((v, w))
            else:
                second.append((v, w))
            cum += w
        a, b = _weighted(first), _weighted(second)
        if a is not None and b is not None:
            hr_drift = {
                "first_half_avg": round(a),
                "second_half_avg": round(b),
                "delta": round(b - a),
            }

    # Temperature (device sensor) in F.
    temps = [float(r["temperature"]) for r in records if r.get("temperature") is not None]
    temperature = None
    if temps:
        avg_c = sum(temps) / len(temps)
        temperature = {
            "avg_f": round(avg_c * 9 / 5 + 32),
            "max_f": round(max(temps) * 9 / 5 + 32),
        }

    # Power:HR decoupling (first vs second half efficiency) — power rides only.
    decoupling_pct = None
    if has_power:
        pw_pairs = [(float(r["power"]), float(r["heart_rate"]), r["_dt"]) for r in records
                    if r.get("power") is not None and r.get("heart_rate") not in (None, 0)
                    and r["_dt"] > 0]
        tw = sum(w for *_, w in pw_pairs)
        if tw > 0:
            half = tw / 2.0
            cum = 0.0
            fp, sp = [], []
            for p, hr, w in pw_pairs:
                (fp if cum < half else sp).append((p, hr, w))
                cum += w

            def eff(rows: list[tuple[float, float, float]]) -> Optional[float]:
                pden = sum(w for *_, w in rows)
                if pden <= 0:
                    return None
                ap = sum(p * w for p, _, w in rows) / pden
                ah = sum(hr * w for _, hr, w in rows) / pden
                return ap / ah if ah > 0 else None

            e1, e2 = eff(fp), eff(sp)
            if e1 and e2:
                decoupling_pct = round((e2 - e1) / e1 * 100.0, 1)

    # ---- owner guess from head unit ----
    product = file_id.get("garmin_product")
    if product is None:
        product = file_id.get("product")
    owner_guess = "jonathan" if product == EDGE_840_PRODUCT else "unknown"

    dist_round = round(dist_mi)
    location_label = region
    type_final = type_label
    needs_location = location_label is None
    needs_type = type_final is None
    proposed = None
    if location_label and type_final and date_local:
        proposed = f"{date_local} {location_label} {type_final} {dist_round}mi.fit"

    # ---- notable suggestion (skill makes the final call) ----
    reasons = []
    if asc_ft >= 3000:
        reasons.append(f"big climbing day ({round(asc_ft):,} ft)")
    if dist_mi >= 55:
        reasons.append(f"very long ({dist_round} mi)")
    if dur_h >= 4.5:
        reasons.append(f"very long duration ({dur_h:.1f} h)")
    borderline = []
    if 2000 <= asc_ft < 3000:
        borderline.append(f"moderate climbing ({round(asc_ft):,} ft)")
    if 4.0 <= dur_h < 4.5:
        borderline.append(f"long duration ({dur_h:.1f} h)")

    return {
        "fit_name_original": fit_path.name,
        "owner_guess": owner_guess,
        "device_product": product,
        "date_local": date_local,
        "utc_start": utc_start.isoformat() if utc_start else None,
        "local_offset_known": local_offset_known,
        "start_lat": round(lat, 5) if lat is not None else None,
        "start_lon": round(lon, 5) if lon is not None else None,
        "region": region,
        "location_label": location_label,
        "type_label": type_final,
        "sport": session.get("sport"),
        "sub_sport": session.get("sub_sport"),
        "needs_location_confirmation": needs_location,
        "needs_type_confirmation": needs_type,
        "distance_mi": round(dist_mi, 2),
        "distance_rounded": dist_round,
        "ascent_ft": round(asc_ft),
        "duration_h": round(dur_h, 2),
        "moving_mph": round(moving_mph, 1) if moving_mph else None,
        "avg_hr": session.get("avg_heart_rate"),
        "max_hr": session.get("max_heart_rate"),
        "has_power": has_power,
        "power": {
            "avg_w": avg_power,
            "np_w": np_power,
            "tss": session.get("training_stress_score"),
            "intensity_factor": session.get("intensity_factor"),
            "total_work_kj": round(session["total_work"] / 1000.0) if session.get("total_work") else None,
        },
        "hr_zones": hr_zones,
        "hr_drift": hr_drift,
        "decoupling_pct": decoupling_pct,
        "temperature_f": temperature,
        "proposed_filename": proposed,
        "notable_suggestion": {
            "is_notable": bool(reasons),
            "borderline": (not reasons) and bool(borderline),
            "reasons": reasons or borderline,
        },
    }


# ---- scan / commit ---------------------------------------------------------

def find_candidate_zips(downloads: Path, explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(z).expanduser() for z in explicit]
    zips = [p for p in downloads.glob("*.zip") if zip_has_fit(p)]
    zips.sort(key=lambda p: p.stat().st_mtime)  # oldest -> newest
    return zips


def target_folder_for(owner: str) -> Path:
    return FOLDER_PARTNER if owner == "partner" else FOLDER_JONATHAN


def cmd_scan(args: argparse.Namespace) -> None:
    downloads = Path(args.downloads).expanduser()
    zips = find_candidate_zips(downloads, args.zip)
    out: dict[str, Any] = {"downloads": str(downloads), "rides": []}

    with tempfile.TemporaryDirectory(prefix="ride_scan_") as tmp:
        workdir = Path(tmp)
        for zp in zips:
            entry: dict[str, Any] = {"zip_path": str(zp), "zip_name": zp.name}
            try:
                fits = extract_fits(zp, workdir)
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"extract failed: {exc}"
                out["rides"].append(entry)
                continue
            if not fits:
                entry["error"] = "no valid FIT inside"
                out["rides"].append(entry)
                continue

            rides = []
            for fp in fits:
                try:
                    stats = parse_ride(fp)
                except Exception as exc:  # noqa: BLE001
                    rides.append({"fit_name_original": fp.name, "error": str(exc)})
                    continue
                # owner resolution: --owner overrides the device guess
                owner = args.owner if args.owner != "auto" else (
                    stats["owner_guess"] if stats["owner_guess"] != "unknown" else "jonathan"
                )
                stats["owner_resolved"] = owner
                folder = target_folder_for(owner)
                stats["target_folder"] = str(folder)
                # collision / duplicate check against the proposed name
                stats["collision"] = {"exists": False, "same_content": False}
                if stats["proposed_filename"]:
                    target = folder / stats["proposed_filename"]
                    if target.exists():
                        same = sha1(target) == sha1(fp)
                        stats["collision"] = {"exists": True, "same_content": same}
                rides.append(stats)
            entry["rides"] = rides
            out["rides"].append(entry)

    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_commit(args: argparse.Namespace) -> None:
    if args.plan:
        plan = json.loads(Path(args.plan).expanduser().read_text())
    else:
        plan = json.loads(sys.stdin.read())

    results = []
    with tempfile.TemporaryDirectory(prefix="ride_commit_") as tmp:
        workdir = Path(tmp)
        for ride in plan.get("rides", []):
            res: dict[str, Any] = {
                "zip_path": ride.get("zip_path"),
                "final_filename": ride.get("final_filename"),
            }
            try:
                zp = Path(ride["zip_path"]).expanduser()
                folder = Path(ride["target_folder"]).expanduser()
                final = ride["final_filename"]
                old_name = ride.get("old_name_for_map", zp.name)

                fits = extract_fits(zp, workdir)
                if not fits:
                    res["status"] = "error"
                    res["detail"] = "no valid FIT inside zip"
                    results.append(res)
                    continue
                # pick the requested member if given, else the single/first fit
                src = fits[0]
                if ride.get("fit_member"):
                    for f in fits:
                        if f.name == ride["fit_member"]:
                            src = f
                            break

                folder.mkdir(parents=True, exist_ok=True)
                target = folder / final
                if target.exists():
                    if sha1(target) == sha1(src):
                        res["status"] = "duplicate"
                        res["detail"] = "identical file already present; deleting zip"
                    else:
                        res["status"] = "error"
                        res["detail"] = "target exists with different content; not overwriting"
                        results.append(res)
                        continue
                else:
                    shutil.copy2(src, target)
                    res["status"] = "imported"

                # append rename-map row
                rename_map = folder / "_rename_map.csv"
                new_file = not rename_map.exists()
                with rename_map.open("a", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    if new_file:
                        w.writerow(["old_name", "new_name"])
                    w.writerow([old_name, final])

                # delete the original zip
                if not args.keep_zip:
                    zp.unlink(missing_ok=True)
                    res["zip_deleted"] = True
                else:
                    res["zip_deleted"] = False

                res["target_path"] = str(target)
            except Exception as exc:  # noqa: BLE001
                res["status"] = "error"
                res["detail"] = str(exc)
            results.append(res)

    json.dump({"results": results}, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="Read-only: find + analyze ride zips, print JSON.")
    s.add_argument("--downloads", default=str(DOWNLOADS))
    s.add_argument("--zip", action="append", default=[],
                   help="Explicit zip path(s) instead of scanning Downloads.")
    s.add_argument("--owner", choices=["auto", "jonathan", "partner"], default="auto")
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("commit", help="Execute a plan (move/rename/log/delete).")
    c.add_argument("--plan", help="Path to plan JSON (else read stdin).")
    c.add_argument("--keep-zip", action="store_true", help="Do not delete the source zip.")
    c.set_defaults(func=cmd_commit)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
