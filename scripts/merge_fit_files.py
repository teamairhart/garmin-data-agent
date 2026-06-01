#!/usr/bin/env python3
"""Merge multiple FIT files (or zipped FIT exports) into one activity FIT.

Use when a single ride got split into parts (e.g. the head unit was started late /
stopped and restarted). Reads every record from each input in time order, rebuilds a
continuous cumulative distance, and writes one Strava/Garmin-Connect-uploadable .fit
with FileId + Record + Lap + Session + Activity messages.

Reads with fitparse (decode); writes with fit_tool (encode).

Usage:
    python scripts/merge_fit_files.py <part1.zip|.fit> <part2...> --output "/path/out.fit"
"""
from __future__ import annotations
import argparse, zipfile, tempfile
from pathlib import Path
from datetime import timezone
from fitparse import FitFile

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.profile_type import (
    FileType, Manufacturer, Sport, SubSport, GarminProduct, SourceType,
)

SC2DEG = 180.0 / 2**31


def extract_fits(inputs, workdir):
    out = []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                for n in zf.namelist():
                    if n.lower().endswith(".fit"):
                        out.append(Path(zf.extract(n, workdir)))
        elif p.suffix.lower() == ".fit":
            out.append(p)
    return out


def read_records(fp):
    recs = []
    for m in FitFile(str(fp)).get_messages("record"):
        d = {f.name: f.value for f in m}
        if d.get("timestamp") is not None:
            recs.append(d)
    recs.sort(key=lambda r: r["timestamp"])
    return recs


def ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round(dt.timestamp() * 1000)


def main():
    ap = argparse.ArgumentParser(description="Merge FIT files/zips into one activity FIT.")
    ap.add_argument("inputs", nargs="+", help="FIT files or zipped FIT exports, in order")
    ap.add_argument("-o", "--output", required=True, help="Output .fit path")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        fits = extract_fits(args.inputs, Path(tmp))
        # read each part, keep order by its own first timestamp
        parts = sorted((read_records(f) for f in fits), key=lambda r: r[0]["timestamp"])

        merged, dist_offset = [], 0.0
        for part in parts:
            base = part[0].get("distance") or 0.0
            last_d = dist_offset
            for r in part:
                d = r.get("distance")
                if d is not None:
                    last_d = dist_offset + (d - base)
                r["_dist"] = last_d
                merged.append(r)
            dist_offset = last_d
        merged.sort(key=lambda r: r["timestamp"])

        builder = FitFileBuilder(auto_define=True, min_string_size=50)

        fid = FileIdMessage()
        fid.type = FileType.ACTIVITY
        fid.manufacturer = Manufacturer.GARMIN.value
        fid.garmin_product = GarminProduct.EDGE_830.value  # barometric Edge → Strava trusts device elevation
        fid.serial_number = 3000000001
        fid.time_created = ms(merged[0]["timestamp"])
        builder.add(fid)

        # device_info identifying a barometric Garmin Edge — without this Strava applies its
        # elevation-basemap correction (under-counts vert). With it, Strava uses device altitude.
        dev = DeviceInfoMessage()
        dev.timestamp = ms(merged[0]["timestamp"])
        dev.device_index = 0  # creator
        dev.manufacturer = Manufacturer.GARMIN.value
        dev.garmin_product = GarminProduct.EDGE_830.value
        dev.product = GarminProduct.EDGE_830.value
        dev.source_type = SourceType.LOCAL
        dev.software_version = 21.0
        dev.serial_number = 3000000001
        builder.add(dev)

        hrs, pws, alts = [], [], []
        for r in merged:
            m = RecordMessage()
            m.timestamp = ms(r["timestamp"])
            lat, lon = r.get("position_lat"), r.get("position_long")
            if lat is not None and lon is not None:
                m.position_lat = lat * SC2DEG
                m.position_long = lon * SC2DEG
            alt = r.get("enhanced_altitude", r.get("altitude"))
            if alt is not None:
                m.altitude = alt; alts.append(alt)
            if r.get("heart_rate") is not None:
                m.heart_rate = r["heart_rate"]; hrs.append(r["heart_rate"])
            if r.get("power") is not None:
                m.power = r["power"]; pws.append(r["power"])
            if r.get("cadence") is not None:
                m.cadence = r["cadence"]
            spd = r.get("enhanced_speed", r.get("speed"))
            if spd is not None:
                m.speed = spd
            m.distance = r["_dist"]
            builder.add(m)

        t0, t1 = merged[0]["timestamp"], merged[-1]["timestamp"]
        elapsed = (t1 - t0).total_seconds()
        ascent = sum(max(0.0, b - a) for a, b in zip(alts, alts[1:])) if len(alts) > 1 else 0

        lap = LapMessage()
        lap.timestamp = ms(t1); lap.start_time = ms(t0)
        lap.total_elapsed_time = elapsed; lap.total_timer_time = elapsed
        lap.total_distance = merged[-1]["_dist"]
        if hrs: lap.avg_heart_rate = round(sum(hrs)/len(hrs)); lap.max_heart_rate = max(hrs)
        builder.add(lap)

        ses = SessionMessage()
        ses.timestamp = ms(t1); ses.start_time = ms(t0)
        ses.total_elapsed_time = elapsed; ses.total_timer_time = elapsed
        ses.total_distance = merged[-1]["_dist"]
        ses.sport = Sport.CYCLING; ses.sub_sport = SubSport.MOUNTAIN
        ses.total_ascent = round(ascent)
        ses.num_laps = 1
        if hrs: ses.avg_heart_rate = round(sum(hrs)/len(hrs)); ses.max_heart_rate = max(hrs)
        if pws: ses.avg_power = round(sum(pws)/len(pws)); ses.max_power = max(pws)
        builder.add(ses)

        act = ActivityMessage()
        act.timestamp = ms(t1); act.total_timer_time = elapsed; act.num_sessions = 1
        builder.add(act)

        out = Path(args.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        builder.build().to_file(str(out))

        print(f"Merged {len(parts)} parts, {len(merged)} records -> {out}")
        print(f"  elapsed {elapsed/3600:.2f} h | dist {merged[-1]['_dist']/1609.34:.1f} mi | ascent ~{ascent*3.281:,.0f} ft")


if __name__ == "__main__":
    main()
