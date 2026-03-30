from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.athlete_profile import load_athlete_profile
from src.training_plan import get_training_day, get_upcoming_training_days, load_training_calendar


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "config" / "athlete_profile.json"
DEFAULT_CALENDAR_PATH = PROJECT_ROOT / "config" / "training_calendar.json"
TRAINING_DAILY_PATHS = [
    PROJECT_ROOT / "exports" / "training_dataset_recent" / "training_daily.csv",
    PROJECT_ROOT / "data" / "training_daily.csv",
]
RECENT_RIDE_PATHS = [
    PROJECT_ROOT / "exports" / "analysis" / "recent_ride_diagnostics.csv",
    PROJECT_ROOT / "data" / "recent_ride_diagnostics.csv",
]


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _load_training_daily() -> pd.DataFrame:
    path = _first_existing(TRAINING_DAILY_PATHS)
    if path is None:
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def _load_recent_rides() -> pd.DataFrame:
    path = _first_existing(RECENT_RIDE_PATHS)
    if path is None:
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    return df


def _build_summary_cards(training_daily: pd.DataFrame) -> dict[str, Any]:
    if training_daily.empty:
        return {
            "last_7d_hours": None,
            "last_7d_tss": None,
            "latest_sleep_hours": None,
            "latest_hrv": None,
            "latest_resting_hr": None,
            "latest_date": None,
        }

    latest_date = training_daily["date"].max()
    recent = training_daily[training_daily["date"].between(latest_date - pd.Timedelta(days=6), latest_date)]
    latest_row = training_daily.sort_values("date").iloc[-1]

    return {
        "last_7d_hours": float(recent.get("garmin_total_timer_hours", pd.Series(dtype=float)).fillna(0).sum()),
        "last_7d_tss": float(recent.get("garmin_total_tss", pd.Series(dtype=float)).fillna(0).sum()),
        "latest_sleep_hours": _safe_float(latest_row.get("sleep_asleep_hours")),
        "latest_hrv": _safe_float(latest_row.get("hrv_sdnn_avg")),
        "latest_resting_hr": _safe_float(latest_row.get("resting_heart_rate_avg")),
        "latest_date": latest_date.strftime("%Y-%m-%d") if pd.notna(latest_date) else None,
    }


def _build_recent_ride_cards(recent_rides: pd.DataFrame) -> dict[str, Any]:
    if recent_rides.empty:
        return {
            "latest_ride": None,
            "latest_climb_cadence": None,
            "latest_threshold_minutes": None,
        }

    latest = recent_rides.sort_values("start_time").iloc[-1]
    recent_rows = recent_rides.sort_values("start_time", ascending=False).head(5).copy()
    if "start_time" in recent_rows.columns:
        recent_rows["start_time_display"] = recent_rows["start_time"].apply(_format_timestamp)
    threshold_minutes = (
        _safe_float(latest.get("time_threshold_flats_power_min"), default=0)
        + _safe_float(latest.get("time_threshold_climbing_power_min"), default=0)
    )
    return {
        "latest_ride": {
            "date": _format_timestamp(latest.get("start_time")),
            "location": latest.get("location_context"),
            "duration_hours": _safe_float(latest.get("duration_hours")),
            "distance_miles": _safe_float(latest.get("distance_miles")),
            "ascent_ft": _safe_float(latest.get("ascent_ft")),
        },
        "latest_climb_cadence": _safe_float(latest.get("climb_avg_cadence_rpm")),
        "latest_threshold_minutes": threshold_minutes,
        "recent_rides": recent_rows.to_dict("records"),
    }


def _build_race_cards(profile: dict[str, Any], today: date) -> list[dict[str, Any]]:
    race_cards: list[dict[str, Any]] = []
    for race in profile.get("race_goals", []):
        race_date = date.fromisoformat(race["date"])
        race_cards.append(
            {
                "name": race["name"],
                "date": race["date"],
                "location": race["location"],
                "days_until": (race_date - today).days,
                "goal": _race_goal_text(race),
            }
        )
    return race_cards


def _race_goal_text(race: dict[str, Any]) -> str:
    if "goal_finish_time_hours_min" in race and "goal_finish_time_hours_max" in race:
        return f"{race['goal_finish_time_hours_min']}-{race['goal_finish_time_hours_max']} hours"
    if "goal_finish_time_hours_max" in race:
        return f"Under {race['goal_finish_time_hours_max']} hours"
    return "Goal not set"


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_timestamp(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def build_dashboard_context(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    profile = load_athlete_profile(DEFAULT_PROFILE_PATH)
    training_days = load_training_calendar(DEFAULT_CALENDAR_PATH)
    training_daily = _load_training_daily()
    recent_rides = _load_recent_rides()

    return {
        "today": today.isoformat(),
        "profile": profile,
        "today_plan": get_training_day(training_days, today),
        "upcoming_plan": get_upcoming_training_days(training_days, today, days=14),
        "summary_cards": _build_summary_cards(training_daily),
        "ride_cards": _build_recent_ride_cards(recent_rides),
        "race_cards": _build_race_cards(profile, today),
    }
