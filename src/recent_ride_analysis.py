from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.athlete_profile import load_athlete_profile

M_TO_MI = 0.000621371
M_TO_FT = 3.28084


def _zone_lookup(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    zones = profile.get("lab_profiles", [{}])[0].get("training_zones", [])
    return {zone["name"]: zone for zone in zones if "name" in zone}


def _classify_location(lat_deg: float, lon_deg: float) -> str:
    if pd.isna(lat_deg) or pd.isna(lon_deg):
        return "unknown"
    if 39.5 <= lat_deg <= 41.5 and -112.5 <= lon_deg <= -110.0:
        return "park_city_region"
    if 34.0 <= lat_deg <= 36.5 and -91.5 <= lon_deg <= -89.0:
        return "memphis_region"
    return "other"


def _weighted_average(frame: pd.DataFrame, value_col: str, weight_col: str = "dt") -> float:
    subset = frame.dropna(subset=[value_col, weight_col])
    if subset.empty or subset[weight_col].sum() <= 0:
        return float("nan")
    return float(np.average(subset[value_col], weights=subset[weight_col]))


def _time_in_range(frame: pd.DataFrame, column: str, lower: float | None, upper: float | None) -> float:
    mask = frame[column].notna()
    if lower is not None:
        mask &= frame[column] >= lower
    if upper is not None:
        mask &= frame[column] <= upper
    return float(frame.loc[mask, "dt"].sum() / 60.0)


def build_recent_ride_analysis(
    session_csv_path: str | Path,
    record_csv_path: str | Path,
    profile_path: str | Path,
    output_path: str | Path,
    start_date: str | None = None,
) -> pd.DataFrame:
    profile = load_athlete_profile(profile_path)
    zone_lookup = _zone_lookup(profile)

    sessions = pd.read_csv(session_csv_path)
    if sessions.empty:
        return pd.DataFrame()

    sessions["start_time"] = pd.to_datetime(sessions["start_time"], errors="coerce")
    sessions["lat_deg"] = pd.to_numeric(sessions["start_position_lat"], errors="coerce") * (180 / 2**31)
    sessions["lon_deg"] = pd.to_numeric(sessions["start_position_long"], errors="coerce") * (180 / 2**31)
    sessions["location_context"] = sessions.apply(
        lambda row: _classify_location(row["lat_deg"], row["lon_deg"]),
        axis=1,
    )

    if start_date:
        start_timestamp = pd.Timestamp(start_date)
        sessions = sessions[sessions["start_time"] >= start_timestamp]

    sessions = sessions.sort_values("start_time").reset_index(drop=True)
    if sessions.empty:
        return pd.DataFrame()

    record_columns = [
        "source_file",
        "timestamp",
        "power",
        "heart_rate",
        "cadence",
        "distance",
        "enhanced_altitude",
    ]
    records = pd.read_csv(record_csv_path, usecols=record_columns, low_memory=False)
    records = records[records["source_file"].isin(sessions["source_file"])].copy()
    records["timestamp"] = pd.to_datetime(records["timestamp"], errors="coerce")
    for column in ["power", "heart_rate", "cadence", "distance", "enhanced_altitude"]:
        records[column] = pd.to_numeric(records[column], errors="coerce")

    rows: list[dict[str, Any]] = []
    for _, session in sessions.iterrows():
        source_file = session["source_file"]
        ride_records = records[records["source_file"] == source_file].sort_values("timestamp").copy()
        if ride_records.empty:
            continue

        ride_records = ride_records.dropna(subset=["timestamp"]).copy()
        ride_records["dt"] = (
            ride_records["timestamp"]
            .diff()
            .dt.total_seconds()
            .fillna(1)
            .clip(lower=0, upper=10)
        )
        ride_records["distance_delta"] = ride_records["distance"].diff()
        ride_records["altitude_delta"] = ride_records["enhanced_altitude"].diff()
        ride_records["grade_pct"] = np.where(
            (ride_records["distance_delta"] > 3) & (ride_records["distance_delta"] < 50),
            (ride_records["altitude_delta"] / ride_records["distance_delta"]) * 100.0,
            np.nan,
        )
        ride_records["grade_pct_smooth"] = (
            ride_records["grade_pct"].rolling(15, center=True, min_periods=5).median()
        )

        climb_records = ride_records[ride_records["grade_pct_smooth"] >= 3.0].copy()

        long_endurance = zone_lookup.get("long_endurance", {})
        medium_endurance = zone_lookup.get("medium_endurance", {})
        threshold_flats = zone_lookup.get("threshold_flats", {})
        threshold_climbing = zone_lookup.get("threshold_climbing", {})

        row = {
            "source_file": source_file,
            "start_time": session["start_time"].isoformat() if pd.notna(session["start_time"]) else None,
            "location_context": session["location_context"],
            "duration_hours": float(pd.to_numeric(session.get("total_timer_time"), errors="coerce") / 3600.0),
            "distance_miles": float(pd.to_numeric(session.get("total_distance"), errors="coerce") * M_TO_MI),
            "ascent_ft": float(pd.to_numeric(session.get("total_ascent"), errors="coerce") * M_TO_FT),
            "avg_power_w": pd.to_numeric(session.get("avg_power"), errors="coerce"),
            "normalized_power_w": pd.to_numeric(session.get("normalized_power"), errors="coerce"),
            "avg_heart_rate_bpm": pd.to_numeric(session.get("avg_heart_rate"), errors="coerce"),
            "max_heart_rate_bpm": pd.to_numeric(session.get("max_heart_rate"), errors="coerce"),
            "avg_cadence_rpm": pd.to_numeric(session.get("avg_cadence"), errors="coerce"),
            "time_long_endurance_power_min": _time_in_range(
                ride_records,
                "power",
                long_endurance.get("power_w_min"),
                long_endurance.get("power_w_max"),
            ),
            "time_medium_endurance_power_min": _time_in_range(
                ride_records,
                "power",
                medium_endurance.get("power_w_min"),
                medium_endurance.get("power_w_max"),
            ),
            "time_threshold_flats_power_min": _time_in_range(
                ride_records,
                "power",
                threshold_flats.get("power_w_min"),
                threshold_flats.get("power_w_max"),
            ),
            "time_threshold_climbing_power_min": _time_in_range(
                ride_records,
                "power",
                threshold_climbing.get("power_w_min"),
                threshold_climbing.get("power_w_max"),
            ),
            "time_threshold_flats_hr_min": _time_in_range(
                ride_records,
                "heart_rate",
                threshold_flats.get("heart_rate_bpm_min"),
                threshold_flats.get("heart_rate_bpm_max"),
            ),
            "time_threshold_climbing_hr_min": _time_in_range(
                ride_records,
                "heart_rate",
                threshold_climbing.get("heart_rate_bpm_min"),
                threshold_climbing.get("heart_rate_bpm_max"),
            ),
            "climb_minutes_ge_3pct": float(climb_records["dt"].sum() / 60.0),
            "climb_avg_grade_pct": _weighted_average(climb_records, "grade_pct_smooth"),
            "climb_avg_power_w": _weighted_average(climb_records, "power"),
            "climb_avg_heart_rate_bpm": _weighted_average(climb_records, "heart_rate"),
            "climb_avg_cadence_rpm": _weighted_average(climb_records, "cadence"),
            "climb_time_cadence_85_95_min": float(
                climb_records.loc[
                    climb_records["cadence"].between(85, 95, inclusive="both"),
                    "dt",
                ].sum()
                / 60.0
            ),
            "climb_time_cadence_lt_75_min": float(
                climb_records.loc[climb_records["cadence"] < 75, "dt"].sum() / 60.0
            ),
        }

        if row["climb_minutes_ge_3pct"] > 0:
            row["climb_cadence_85_95_pct"] = (
                row["climb_time_cadence_85_95_min"] / row["climb_minutes_ge_3pct"]
            )
        else:
            row["climb_cadence_85_95_pct"] = float("nan")

        rows.append(row)

    diagnostics = pd.DataFrame(rows).sort_values("start_time").reset_index(drop=True)
    output_file = Path(output_path).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(output_file, index=False)
    return diagnostics
