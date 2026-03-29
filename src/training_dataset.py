from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd


GARMIN_ZERO_FILL_COLUMNS = [
    "garmin_ride_count",
    "garmin_total_distance_m",
    "garmin_total_timer_time_s",
    "garmin_total_work_j",
    "garmin_total_tss",
    "garmin_total_ascent_m",
    "garmin_total_descent_m",
]

APPLE_ZERO_FILL_COLUMNS = [
    "apple_workout_count",
    "apple_workout_duration_seconds",
    "apple_workout_total_energy_burned",
    "apple_workout_total_distance",
    "sleep_asleep_seconds",
    "sleep_in_bed_seconds",
    "sleep_awake_seconds",
]


def _load_garmin_daily_summary(file_summary_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(file_summary_path)
    if df.empty:
        return pd.DataFrame(columns=["date"])

    timestamp_series = pd.to_datetime(
        df["start_time"].fillna(df["activity_time_created"]),
        errors="coerce",
    )
    df = df.assign(date=timestamp_series.dt.date.astype("string"))

    numeric_columns = [
        "total_distance_m",
        "total_timer_time_s",
        "avg_speed_mps",
        "max_speed_mps",
        "avg_power_w",
        "max_power_w",
        "normalized_power_w",
        "threshold_power_w",
        "intensity_factor",
        "total_work_j",
        "avg_heart_rate_bpm",
        "max_heart_rate_bpm",
        "total_ascent_m",
        "total_descent_m",
        "training_stress_score",
        "total_training_effect",
        "total_anaerobic_training_effect",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    grouped = (
        df.dropna(subset=["date"])
        .groupby("date", dropna=False)
        .agg(
            garmin_ride_count=("source_file", "count"),
            garmin_total_distance_m=("total_distance_m", "sum"),
            garmin_total_timer_time_s=("total_timer_time_s", "sum"),
            garmin_avg_speed_mps=("avg_speed_mps", "mean"),
            garmin_max_speed_mps=("max_speed_mps", "max"),
            garmin_avg_power_w=("avg_power_w", "mean"),
            garmin_max_power_w=("max_power_w", "max"),
            garmin_avg_heart_rate_bpm=("avg_heart_rate_bpm", "mean"),
            garmin_max_heart_rate_bpm=("max_heart_rate_bpm", "max"),
            garmin_total_ascent_m=("total_ascent_m", "sum"),
            garmin_total_descent_m=("total_descent_m", "sum"),
            garmin_total_tss=("training_stress_score", "sum"),
            garmin_total_work_j=("total_work_j", "sum"),
            garmin_threshold_power_w=("threshold_power_w", "max"),
            garmin_intensity_factor_mean=("intensity_factor", "mean"),
            garmin_total_training_effect=("total_training_effect", "sum"),
            garmin_total_anaerobic_training_effect=("total_anaerobic_training_effect", "sum"),
        )
        .reset_index()
    )
    return grouped


def _load_apple_daily_metrics(daily_metrics_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(daily_metrics_path)
    if df.empty:
        return pd.DataFrame(columns=["date"])

    df["date"] = df["date"].astype("string")
    for column in df.columns:
        if column == "date":
            continue
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def _ensure_contiguous_days(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    date_index = pd.to_datetime(df["date"], errors="coerce")
    min_date = date_index.min()
    max_date = date_index.max()
    if pd.isna(min_date) or pd.isna(max_date):
        return df

    full_range = pd.date_range(min_date, max_date, freq="D")
    expanded = (
        df.assign(date=pd.to_datetime(df["date"], errors="coerce"))
        .set_index("date")
        .reindex(full_range)
        .rename_axis("date")
        .reset_index()
    )
    expanded["date"] = expanded["date"].dt.strftime("%Y-%m-%d")
    return expanded


def build_training_dataset(
    garmin_file_summary_path: str | Path,
    apple_daily_metrics_path: str | Path,
    output_path: str | Path,
) -> pd.DataFrame:
    garmin_df = _load_garmin_daily_summary(garmin_file_summary_path)
    apple_df = _load_apple_daily_metrics(apple_daily_metrics_path)

    merged = pd.merge(garmin_df, apple_df, on="date", how="outer")
    merged = _ensure_contiguous_days(merged).sort_values("date").reset_index(drop=True)

    for column in GARMIN_ZERO_FILL_COLUMNS + APPLE_ZERO_FILL_COLUMNS:
        if column in merged.columns:
            merged[column] = merged[column].fillna(0)

    if "garmin_total_timer_time_s" in merged.columns:
        merged["garmin_total_timer_hours"] = merged["garmin_total_timer_time_s"] / 3600.0
    if "sleep_asleep_seconds" in merged.columns:
        merged["sleep_asleep_hours"] = merged["sleep_asleep_seconds"] / 3600.0
    if "sleep_in_bed_seconds" in merged.columns:
        merged["sleep_in_bed_hours"] = merged["sleep_in_bed_seconds"] / 3600.0

    if "garmin_total_tss" in merged.columns:
        merged["garmin_total_tss_prev_day"] = merged["garmin_total_tss"].shift(1)
        merged["garmin_total_tss_7d"] = merged["garmin_total_tss"].rolling(7, min_periods=1).sum()

    if "garmin_total_timer_hours" in merged.columns:
        merged["garmin_total_timer_hours_prev_day"] = merged["garmin_total_timer_hours"].shift(1)
        merged["garmin_total_timer_hours_7d"] = merged["garmin_total_timer_hours"].rolling(7, min_periods=1).sum()

    for column in ["sleep_asleep_hours", "hrv_sdnn_avg", "resting_heart_rate_avg"]:
        if column in merged.columns:
            baseline = merged[column].rolling(7, min_periods=3).mean().shift(1)
            merged[f"{column}_7d_avg"] = baseline
            merged[f"{column}_vs_7d"] = merged[column] - baseline

    output_file = Path(output_path).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_file, index=False)
    return merged
