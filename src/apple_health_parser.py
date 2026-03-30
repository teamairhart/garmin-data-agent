from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


APPLE_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
)


STATS_RECORD_TYPES = {
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv_sdnn",
    "HKQuantityTypeIdentifierWalkingHeartRateAverage": "walking_heart_rate_average",
    "HKQuantityTypeIdentifierRespiratoryRate": "respiratory_rate",
    "HKQuantityTypeIdentifierOxygenSaturation": "oxygen_saturation",
    "HKQuantityTypeIdentifierVO2Max": "vo2_max",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": "sleeping_wrist_temperature",
}

SUM_RECORD_TYPES = {
    "HKQuantityTypeIdentifierStepCount": "step_count",
    "HKQuantityTypeIdentifierDistanceWalkingRunning": "distance_walking_running",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy_burned",
    "HKQuantityTypeIdentifierBasalEnergyBurned": "basal_energy_burned",
    "HKQuantityTypeIdentifierFlightsClimbed": "flights_climbed",
    "HKQuantityTypeIdentifierAppleExerciseTime": "exercise_time",
}

LATEST_RECORD_TYPES = {
    "HKQuantityTypeIdentifierBodyMass": "body_mass",
    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat_percentage",
    "HKQuantityTypeIdentifierLeanBodyMass": "lean_body_mass",
}

SLEEP_RECORD_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"
SLEEP_CATEGORY_MAP = {
    0: "in_bed",
    1: "asleep",
    2: "awake",
    3: "asleep_core",
    4: "asleep_deep",
    5: "asleep_rem",
}

SLEEP_CATEGORY_TEXT_MAP = {
    "HKCategoryValueSleepAnalysisInBed": "in_bed",
    "HKCategoryValueSleepAnalysisAsleep": "asleep",
    "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisAsleepCore": "asleep_core",
    "HKCategoryValueSleepAnalysisAsleepDeep": "asleep_deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "asleep_rem",
}

ASLEEP_SLEEP_VALUES = {1, 3, 4, 5}
ASLEEP_SLEEP_STAGE_NAMES = {"asleep", "asleep_core", "asleep_deep", "asleep_rem"}


@dataclass
class AppleSchema:
    field_names: set[str] = field(default_factory=set)
    row_count: int = 0


def snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return value.strip("_").lower()


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return slug or "unknown"


def shorten_apple_type_name(type_name: str) -> str:
    cleaned = re.sub(r"^HK(?:Quantity|Category|Correlation|Data|Workout)TypeIdentifier", "", type_name)
    cleaned = re.sub(r"^HK", "", cleaned)
    return snake_case(cleaned) or safe_slug(type_name)


def parse_apple_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value

    for date_format in APPLE_DATE_FORMATS:
        try:
            return datetime.strptime(str(value), date_format)
        except ValueError:
            continue

    return None


def parse_cutoff_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    return datetime.strptime(str(value), "%Y-%m-%d").date()


def normalize_xml_value(value: Any) -> Any:
    if value in (None, ""):
        return None

    if isinstance(value, (int, float, bool)):
        return value

    parsed_datetime = parse_apple_datetime(value)
    if parsed_datetime is not None:
        return parsed_datetime.isoformat()

    string_value = str(value)
    try:
        numeric_value = float(string_value)
    except ValueError:
        return string_value

    return int(numeric_value) if numeric_value.is_integer() else numeric_value


def coerce_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def strip_namespace(tag: str) -> str:
    return tag.split("}", 1)[-1]


def metadata_entries_to_json(element: ET.Element) -> Optional[str]:
    metadata: Dict[str, Any] = {}

    for child in element:
        child_tag = strip_namespace(child.tag)
        if child_tag != "MetadataEntry":
            continue

        key = child.attrib.get("key")
        if not key:
            continue
        metadata[key] = normalize_xml_value(child.attrib.get("value"))

    if not metadata:
        return None

    return json.dumps(metadata, sort_keys=True)


def workout_events_to_json(element: ET.Element) -> Optional[str]:
    events: List[Dict[str, Any]] = []

    for child in element:
        child_tag = strip_namespace(child.tag)
        if child_tag != "WorkoutEvent":
            continue
        events.append({snake_case(key): normalize_xml_value(value) for key, value in child.attrib.items()})

    if not events:
        return None

    return json.dumps(events)


def element_to_row(element: ET.Element) -> Dict[str, Any]:
    row = {snake_case(key): normalize_xml_value(value) for key, value in element.attrib.items()}

    metadata_json = metadata_entries_to_json(element)
    if metadata_json:
        row["metadata_json"] = metadata_json

    workout_events_json = workout_events_to_json(element)
    if workout_events_json:
        row["workout_events_json"] = workout_events_json

    start_dt = parse_apple_datetime(row.get("start_date"))
    end_dt = parse_apple_datetime(row.get("end_date"))
    if start_dt and end_dt:
        row["duration_seconds"] = max((end_dt - start_dt).total_seconds(), 0.0)

    return row


def iter_apple_health_rows(xml_path: str | Path) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    export_path = Path(xml_path).expanduser().resolve()
    context = ET.iterparse(export_path, events=("end",))

    for _, element in context:
        tag = strip_namespace(element.tag)

        if tag == "Record":
            row = element_to_row(element)
            record_type = str(row.get("type") or "unknown_record")
            row["record_type"] = record_type
            yield ("record", record_type, row)
        elif tag == "Workout":
            row = element_to_row(element)
            yield ("workout", "workout", row)
        elif tag == "ActivitySummary":
            row = element_to_row(element)
            yield ("activity_summary", "activity_summary", row)
        elif tag == "ClinicalRecord":
            row = element_to_row(element)
            yield ("clinical_record", "clinical_record", row)

        element.clear()


def _scan_apple_export(
    xml_path: str | Path,
    cutoff_date: Optional[date] = None,
) -> Tuple[Dict[str, AppleSchema], Dict[str, AppleSchema], Counter]:
    record_schemas: Dict[str, AppleSchema] = defaultdict(AppleSchema)
    table_schemas: Dict[str, AppleSchema] = defaultdict(AppleSchema)
    counters: Counter = Counter()

    for element_type, subtype, row in iter_apple_health_rows(xml_path):
        if not _passes_cutoff(element_type, row, cutoff_date):
            continue
        counters[f"{element_type}_rows"] += 1

        if element_type == "record":
            schema = record_schemas[subtype]
        else:
            schema = table_schemas[element_type]

        schema.row_count += 1
        schema.field_names.update(row.keys())

    return record_schemas, table_schemas, counters


def _default_daily_row() -> Dict[str, Any]:
    return {
        "sleep_asleep_seconds": 0.0,
        "sleep_in_bed_seconds": 0.0,
        "sleep_awake_seconds": 0.0,
        "apple_workout_count": 0,
        "apple_workout_duration_seconds": 0.0,
        "apple_workout_total_energy_burned": 0.0,
        "apple_workout_total_distance": 0.0,
    }


def _stats_update(day_row: Dict[str, Any], metric_name: str, value: Optional[float]) -> None:
    if value is None:
        return

    sum_key = f"{metric_name}_sum"
    count_key = f"{metric_name}_count"
    min_key = f"{metric_name}_min"
    max_key = f"{metric_name}_max"

    day_row[sum_key] = day_row.get(sum_key, 0.0) + value
    day_row[count_key] = day_row.get(count_key, 0) + 1
    day_row[min_key] = value if min_key not in day_row else min(day_row[min_key], value)
    day_row[max_key] = value if max_key not in day_row else max(day_row[max_key], value)


def _sum_update(day_row: Dict[str, Any], metric_name: str, value: Optional[float]) -> None:
    if value is None:
        return
    sum_key = f"{metric_name}_sum"
    day_row[sum_key] = day_row.get(sum_key, 0.0) + value


def _latest_update(day_row: Dict[str, Any], metric_name: str, value: Optional[float], when: Optional[datetime]) -> None:
    if value is None:
        return

    ts_key = f"{metric_name}_timestamp"
    value_key = f"{metric_name}_latest"

    if ts_key not in day_row or (when is not None and day_row[ts_key] <= when):
        day_row[ts_key] = when or datetime.min
        day_row[value_key] = value


def _sleep_update(day_row: Dict[str, Any], row: Dict[str, Any]) -> None:
    duration_seconds = coerce_float(row.get("duration_seconds"))
    if duration_seconds is None:
        return

    raw_value = row.get("value")
    if isinstance(raw_value, str) and raw_value in SLEEP_CATEGORY_TEXT_MAP:
        stage_name = SLEEP_CATEGORY_TEXT_MAP[raw_value]
    else:
        value_code = int(coerce_float(raw_value) or 0)
        stage_name = SLEEP_CATEGORY_MAP.get(value_code, f"value_{value_code}")
    day_row[f"sleep_{stage_name}_seconds"] = day_row.get(f"sleep_{stage_name}_seconds", 0.0) + duration_seconds

    if stage_name in ASLEEP_SLEEP_STAGE_NAMES:
        day_row["sleep_asleep_seconds"] += duration_seconds
    elif stage_name == "in_bed":
        day_row["sleep_in_bed_seconds"] += duration_seconds
    elif stage_name == "awake":
        day_row["sleep_awake_seconds"] += duration_seconds


def _update_daily_metrics_from_record(
    daily_rows: Dict[str, Dict[str, Any]],
    row: Dict[str, Any],
) -> None:
    record_type = row.get("record_type")
    if record_type not in STATS_RECORD_TYPES and record_type not in SUM_RECORD_TYPES and record_type not in LATEST_RECORD_TYPES and record_type != SLEEP_RECORD_TYPE:
        return

    anchor_date = _row_anchor_date("record", row)
    if anchor_date is None:
        return

    end_dt = parse_apple_datetime(row.get("end_date"))
    start_dt = parse_apple_datetime(row.get("start_date"))
    creation_dt = parse_apple_datetime(row.get("creation_date"))
    anchor_dt = end_dt or start_dt or creation_dt

    day_key = anchor_date.isoformat()
    day_row = daily_rows.setdefault(day_key, _default_daily_row())
    day_row["date"] = day_key

    numeric_value = coerce_float(row.get("value"))

    if record_type == SLEEP_RECORD_TYPE:
        _sleep_update(day_row, row)
        return

    if record_type in STATS_RECORD_TYPES:
        _stats_update(day_row, STATS_RECORD_TYPES[record_type], numeric_value)
    elif record_type in SUM_RECORD_TYPES:
        _sum_update(day_row, SUM_RECORD_TYPES[record_type], numeric_value)
    elif record_type in LATEST_RECORD_TYPES:
        _latest_update(day_row, LATEST_RECORD_TYPES[record_type], numeric_value, anchor_dt)


def _update_daily_metrics_from_workout(
    daily_rows: Dict[str, Dict[str, Any]],
    row: Dict[str, Any],
) -> None:
    anchor_date = _row_anchor_date("workout", row)
    if anchor_date is None:
        return

    day_key = anchor_date.isoformat()
    day_row = daily_rows.setdefault(day_key, _default_daily_row())
    day_row["date"] = day_key

    day_row["apple_workout_count"] += 1
    day_row["apple_workout_duration_seconds"] += coerce_float(row.get("duration_seconds")) or 0.0
    day_row["apple_workout_total_energy_burned"] += coerce_float(row.get("total_energy_burned")) or 0.0
    day_row["apple_workout_total_distance"] += coerce_float(row.get("total_distance")) or 0.0


def _update_daily_metrics_from_activity_summary(
    daily_rows: Dict[str, Dict[str, Any]],
    row: Dict[str, Any],
) -> None:
    summary_date = row.get("date_components")
    if not summary_date:
        summary_date = "-".join(
            [
                str(int(row.get("date_components_year", 0) or 0)).zfill(4),
                str(int(row.get("date_components_month", 0) or 0)).zfill(2),
                str(int(row.get("date_components_day", 0) or 0)).zfill(2),
            ]
        )

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", summary_date):
        return

    day_row = daily_rows.setdefault(summary_date, _default_daily_row())
    day_row["date"] = summary_date
    day_row["activity_summary_active_energy_burned"] = coerce_float(row.get("active_energy_burned"))
    day_row["activity_summary_active_energy_burned_goal"] = coerce_float(row.get("active_energy_burned_goal"))
    day_row["activity_summary_apple_exercise_time"] = coerce_float(row.get("apple_exercise_time"))
    day_row["activity_summary_apple_exercise_time_goal"] = coerce_float(row.get("apple_exercise_time_goal"))
    day_row["activity_summary_apple_stand_hours"] = coerce_float(row.get("apple_stand_hours"))
    day_row["activity_summary_apple_stand_hours_goal"] = coerce_float(row.get("apple_stand_hours_goal"))


def _row_anchor_date(element_type: str, row: Dict[str, Any]) -> Optional[date]:
    if element_type == "activity_summary":
        summary_date = row.get("date_components")
        if summary_date and re.match(r"^\d{4}-\d{2}-\d{2}$", str(summary_date)):
            return datetime.strptime(str(summary_date), "%Y-%m-%d").date()
        return None

    start_dt = parse_apple_datetime(row.get("start_date"))
    end_dt = parse_apple_datetime(row.get("end_date"))
    creation_dt = parse_apple_datetime(row.get("creation_date"))

    if element_type == "record" and row.get("record_type") == SLEEP_RECORD_TYPE:
        anchor_dt = end_dt or start_dt or creation_dt
    else:
        anchor_dt = end_dt or start_dt or creation_dt

    return anchor_dt.date() if anchor_dt else None


def _passes_cutoff(element_type: str, row: Dict[str, Any], cutoff_date: Optional[date]) -> bool:
    if cutoff_date is None:
        return True

    anchor_date = _row_anchor_date(element_type, row)
    if anchor_date is None:
        return False

    return anchor_date >= cutoff_date


def _finalize_daily_rows(daily_rows: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    finalized_rows: List[Dict[str, Any]] = []

    for day_key in sorted(daily_rows):
        row = dict(daily_rows[day_key])

        for metric_name in STATS_RECORD_TYPES.values():
            sum_key = f"{metric_name}_sum"
            count_key = f"{metric_name}_count"
            avg_key = f"{metric_name}_avg"
            count = row.get(count_key)
            if count:
                row[avg_key] = row[sum_key] / count

        for metric_name in LATEST_RECORD_TYPES.values():
            row.pop(f"{metric_name}_timestamp", None)

        finalized_rows.append(row)

    return finalized_rows


def export_apple_health_xml(
    xml_path: str | Path,
    output_dir: str | Path,
    cutoff_date: Any = None,
) -> Dict[str, Any]:
    export_path = Path(xml_path).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    cutoff = parse_cutoff_date(cutoff_date)

    record_schemas, table_schemas, counters = _scan_apple_export(export_path, cutoff_date=cutoff)

    record_dir = output_path / "record_types"
    record_dir.mkdir(parents=True, exist_ok=True)

    writers: Dict[Tuple[str, str], csv.DictWriter] = {}
    handles: List[Any] = []
    daily_rows: Dict[str, Dict[str, Any]] = {}

    try:
        for record_type in sorted(record_schemas):
            schema = record_schemas[record_type]
            filename = f"{shorten_apple_type_name(record_type)}.csv"
            handle = (record_dir / filename).open("w", newline="", encoding="utf-8")
            handles.append(handle)
            writer = csv.DictWriter(handle, fieldnames=sorted(schema.field_names))
            writer.writeheader()
            writers[("record", record_type)] = writer

        for table_name in sorted(table_schemas):
            schema = table_schemas[table_name]
            handle = (output_path / f"{table_name}.csv").open("w", newline="", encoding="utf-8")
            handles.append(handle)
            writer = csv.DictWriter(handle, fieldnames=sorted(schema.field_names))
            writer.writeheader()
            writers[(table_name, table_name)] = writer

        for element_type, subtype, row in iter_apple_health_rows(export_path):
            if not _passes_cutoff(element_type, row, cutoff):
                continue
            if element_type == "record":
                writers[(element_type, subtype)].writerow(row)
                _update_daily_metrics_from_record(daily_rows, row)
            else:
                writers[(element_type, element_type)].writerow(row)
                if element_type == "workout":
                    _update_daily_metrics_from_workout(daily_rows, row)
                elif element_type == "activity_summary":
                    _update_daily_metrics_from_activity_summary(daily_rows, row)
    finally:
        for handle in handles:
            handle.close()

    daily_metrics_rows = _finalize_daily_rows(daily_rows)
    daily_metrics_path = output_path / "daily_metrics.csv"
    if daily_metrics_rows:
        fieldnames = sorted({key for row in daily_metrics_rows for key in row.keys()})
        with daily_metrics_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in daily_metrics_rows:
                writer.writerow(row)

    record_catalog_path = output_path / "record_catalog.csv"
    with record_catalog_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["record_type", "csv_file", "row_count", "field_count", "fields_json"],
        )
        writer.writeheader()
        for record_type in sorted(record_schemas):
            schema = record_schemas[record_type]
            writer.writerow(
                {
                    "record_type": record_type,
                    "csv_file": f"record_types/{shorten_apple_type_name(record_type)}.csv",
                    "row_count": schema.row_count,
                    "field_count": len(schema.field_names),
                    "fields_json": json.dumps(sorted(schema.field_names)),
                }
            )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(export_path),
        "output_dir": str(output_path),
        "cutoff_date": cutoff.isoformat() if cutoff else None,
        "record_type_count": len(record_schemas),
        "record_row_count": counters.get("record_rows", 0),
        "workout_row_count": counters.get("workout_rows", 0),
        "activity_summary_row_count": counters.get("activity_summary_rows", 0),
        "clinical_record_row_count": counters.get("clinical_record_rows", 0),
        "record_types": {
            record_type: {
                "csv_file": f"record_types/{shorten_apple_type_name(record_type)}.csv",
                "row_count": schema.row_count,
                "field_count": len(schema.field_names),
                "fields": sorted(schema.field_names),
            }
            for record_type, schema in sorted(record_schemas.items())
        },
        "tables": {
            table_name: {
                "csv_file": f"{table_name}.csv",
                "row_count": schema.row_count,
                "field_count": len(schema.field_names),
                "fields": sorted(schema.field_names),
            }
            for table_name, schema in sorted(table_schemas.items())
        },
    }

    (output_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
