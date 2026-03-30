from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrainingDay:
    date: str
    block_name: str
    location: str
    headline: str
    prescriptions: list[dict[str, Any]]


def load_training_calendar(calendar_path: str | Path) -> list[TrainingDay]:
    path = Path(calendar_path).expanduser().resolve()
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    training_days: list[TrainingDay] = []
    for block in payload.get("blocks", []):
        start = date.fromisoformat(block["start_date"])
        end = date.fromisoformat(block["end_date"])
        for day_def in block.get("days", []):
            target_date = start + timedelta(days=int(day_def["offset"]))
            if target_date > end:
                continue
            training_days.append(
                TrainingDay(
                    date=target_date.isoformat(),
                    block_name=block["name"],
                    location=block["location"],
                    headline=day_def["headline"],
                    prescriptions=day_def.get("prescriptions", []),
                )
            )

    training_days.sort(key=lambda training_day: training_day.date)
    return training_days


def get_training_day(training_days: list[TrainingDay], target_date: date) -> TrainingDay | None:
    target = target_date.isoformat()
    for training_day in training_days:
        if training_day.date == target:
            return training_day
    return None


def get_upcoming_training_days(
    training_days: list[TrainingDay],
    start_date: date,
    days: int = 14,
) -> list[TrainingDay]:
    end_date = start_date + timedelta(days=days - 1)
    return [
        training_day
        for training_day in training_days
        if start_date.isoformat() <= training_day.date <= end_date.isoformat()
    ]
