from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import pandas as pd
from fitparse import FitFile


EXPORT_METADATA_COLUMNS = [
    "source_file",
    "source_path",
    "message_name",
    "message_number",
    "message_index",
    "message_index_within_type",
]


@dataclass
class FieldCatalog:
    definition_numbers: set[int] = field(default_factory=set)
    units: set[str] = field(default_factory=set)
    value_types: set[str] = field(default_factory=set)


@dataclass
class MessageCatalog:
    field_names: set[str] = field(default_factory=set)
    field_catalog: Dict[str, FieldCatalog] = field(default_factory=dict)
    row_count: int = 0
    message_numbers: set[int] = field(default_factory=set)

    def ensure_field(self, field_name: str) -> FieldCatalog:
        if field_name not in self.field_catalog:
            self.field_catalog[field_name] = FieldCatalog()
        return self.field_catalog[field_name]


def iter_fit_files(input_dir: str | Path, recursive: bool = True) -> Iterator[Path]:
    base_path = Path(input_dir).expanduser().resolve()
    pattern = "**/*.fit" if recursive else "*.fit"

    for path in sorted(base_path.glob(pattern)):
        if path.is_file():
            yield path


def normalize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, bytes):
        return value.hex()

    if isinstance(value, dict):
        return json.dumps(
            {str(key): normalize_value(item) for key, item in value.items()},
            sort_keys=True,
        )

    if isinstance(value, (list, tuple, set)):
        return json.dumps([normalize_value(item) for item in value])

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except TypeError:
            pass

    return str(value)


def resolve_message_name(message: Any) -> str:
    message_name = getattr(message, "name", None)
    if message_name:
        return str(message_name)

    mesg_num = getattr(message, "mesg_num", None)
    if mesg_num is not None:
        return f"unknown_{mesg_num}"

    return "unknown_message"


def safe_message_slug(message_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", message_name.strip())
    return slug or "unknown_message"


def extract_message_values(
    message: Iterable[Any],
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    values: Dict[str, Any] = {}
    metadata: Dict[str, Dict[str, Any]] = {}

    for field_data in message:
        field_name = getattr(field_data, "name", None)
        if not field_name:
            continue

        values[field_name] = normalize_value(getattr(field_data, "value", None))
        metadata[field_name] = {
            "definition_number": getattr(field_data, "def_num", None),
            "units": getattr(field_data, "units", None),
            "value_type": type(getattr(field_data, "value", None)).__name__,
        }

    return values, metadata


def load_single_fit_activity(fit_file_path: str | Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    fit_file = FitFile(str(fit_file_path))

    records: List[Dict[str, Any]] = []
    for message in fit_file.get_messages("record"):
        values, _ = extract_message_values(message)
        records.append(values)

    session_data: Dict[str, Any] = {}
    for message in fit_file.get_messages("session"):
        values, _ = extract_message_values(message)
        session_data = values
        break

    return pd.DataFrame(records), session_data


def build_file_summary_row(
    file_path: Path,
    message_counts: Counter,
    session_data: Dict[str, Any],
    file_id_data: Dict[str, Any],
    parse_error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "source_file": file_path.name,
        "source_path": str(file_path),
        "parse_error": parse_error or "",
        "total_messages": int(sum(message_counts.values())),
        "message_type_count": len(message_counts),
        "message_counts_json": json.dumps(dict(sorted(message_counts.items()))),
        "activity_time_created": file_id_data.get("time_created"),
        "activity_type": file_id_data.get("type"),
        "manufacturer": file_id_data.get("manufacturer"),
        "garmin_product": file_id_data.get("garmin_product"),
        "serial_number": file_id_data.get("serial_number"),
        "start_time": session_data.get("start_time"),
        "sport": session_data.get("sport"),
        "sub_sport": session_data.get("sub_sport"),
        "total_distance_m": session_data.get("total_distance"),
        "total_timer_time_s": session_data.get("total_timer_time"),
        "avg_speed_mps": session_data.get("enhanced_avg_speed", session_data.get("avg_speed")),
        "max_speed_mps": session_data.get("enhanced_max_speed", session_data.get("max_speed")),
        "avg_power_w": session_data.get("avg_power"),
        "max_power_w": session_data.get("max_power"),
        "normalized_power_w": session_data.get("normalized_power"),
        "threshold_power_w": session_data.get("threshold_power"),
        "intensity_factor": session_data.get("intensity_factor"),
        "total_work_j": session_data.get("total_work"),
        "avg_heart_rate_bpm": session_data.get("avg_heart_rate"),
        "max_heart_rate_bpm": session_data.get("max_heart_rate"),
        "total_ascent_m": session_data.get("total_ascent"),
        "total_descent_m": session_data.get("total_descent"),
        "training_stress_score": session_data.get("training_stress_score"),
        "total_training_effect": session_data.get("total_training_effect"),
        "total_anaerobic_training_effect": session_data.get("total_anaerobic_training_effect"),
    }


def _scan_fit_folder(
    input_dir: str | Path,
    recursive: bool = True,
) -> Tuple[Dict[str, MessageCatalog], List[Dict[str, Any]], List[Dict[str, str]]]:
    message_catalog: Dict[str, MessageCatalog] = defaultdict(MessageCatalog)
    file_summaries: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for file_path in iter_fit_files(input_dir=input_dir, recursive=recursive):
        message_counts: Counter = Counter()
        session_data: Dict[str, Any] = {}
        file_id_data: Dict[str, Any] = {}

        try:
            fit_file = FitFile(str(file_path))
            for message in fit_file.get_messages():
                message_name = resolve_message_name(message)
                message_number = getattr(message, "mesg_num", None)
                values, metadata = extract_message_values(message)

                catalog = message_catalog[message_name]
                catalog.row_count += 1
                message_counts[message_name] += 1
                if message_number is not None:
                    catalog.message_numbers.add(int(message_number))

                for field_name, value in values.items():
                    catalog.field_names.add(field_name)
                    field_catalog = catalog.ensure_field(field_name)

                    definition_number = metadata[field_name]["definition_number"]
                    if definition_number is not None:
                        field_catalog.definition_numbers.add(int(definition_number))

                    units = metadata[field_name]["units"]
                    if units:
                        field_catalog.units.add(str(units))

                    value_type = metadata[field_name]["value_type"]
                    if value_type:
                        field_catalog.value_types.add(value_type)

                if message_name == "session" and not session_data:
                    session_data = values
                elif message_name == "file_id" and not file_id_data:
                    file_id_data = values

            file_summaries.append(
                build_file_summary_row(
                    file_path=file_path,
                    message_counts=message_counts,
                    session_data=session_data,
                    file_id_data=file_id_data,
                )
            )
        except Exception as exc:
            error = {"source_file": file_path.name, "source_path": str(file_path), "error": str(exc)}
            errors.append(error)
            file_summaries.append(
                build_file_summary_row(
                    file_path=file_path,
                    message_counts=message_counts,
                    session_data=session_data,
                    file_id_data=file_id_data,
                    parse_error=str(exc),
                )
            )

    return message_catalog, file_summaries, errors


def _write_file_summaries(output_dir: Path, file_summaries: List[Dict[str, Any]]) -> None:
    summary_path = output_dir / "file_summary.csv"
    fieldnames = [
        "source_file",
        "source_path",
        "parse_error",
        "total_messages",
        "message_type_count",
        "message_counts_json",
        "activity_time_created",
        "activity_type",
        "manufacturer",
        "garmin_product",
        "serial_number",
        "start_time",
        "sport",
        "sub_sport",
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

    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in file_summaries:
            writer.writerow(row)


def _write_message_catalog(output_dir: Path, message_catalog: Dict[str, MessageCatalog]) -> None:
    catalog_path = output_dir / "message_catalog.csv"
    fieldnames = [
        "message_name",
        "message_numbers",
        "row_count",
        "field_count",
        "csv_file",
        "fields_json",
    ]

    with catalog_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for message_name in sorted(message_catalog):
            catalog = message_catalog[message_name]
            writer.writerow(
                {
                    "message_name": message_name,
                    "message_numbers": json.dumps(sorted(catalog.message_numbers)),
                    "row_count": catalog.row_count,
                    "field_count": len(catalog.field_names),
                    "csv_file": f"messages/{safe_message_slug(message_name)}.csv",
                    "fields_json": json.dumps(sorted(catalog.field_names)),
                }
            )


def _build_manifest(
    input_dir: Path,
    output_dir: Path,
    message_catalog: Dict[str, MessageCatalog],
    file_summaries: List[Dict[str, Any]],
    errors: List[Dict[str, str]],
) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "total_fit_files": len(file_summaries),
        "successful_files": sum(1 for row in file_summaries if not row["parse_error"]),
        "failed_files": sum(1 for row in file_summaries if row["parse_error"]),
        "message_type_count": len(message_catalog),
        "message_types": {},
        "errors": errors,
    }

    for message_name in sorted(message_catalog):
        catalog = message_catalog[message_name]
        manifest["message_types"][message_name] = {
            "csv_file": f"messages/{safe_message_slug(message_name)}.csv",
            "message_numbers": sorted(catalog.message_numbers),
            "row_count": catalog.row_count,
            "field_count": len(catalog.field_names),
            "fields": [
                {
                    "name": field_name,
                    "definition_numbers": sorted(catalog.field_catalog[field_name].definition_numbers),
                    "units": sorted(catalog.field_catalog[field_name].units),
                    "value_types": sorted(catalog.field_catalog[field_name].value_types),
                }
                for field_name in sorted(catalog.field_names)
            ],
        }

    return manifest


def export_fit_folder(
    input_dir: str | Path,
    output_dir: str | Path,
    recursive: bool = True,
) -> Dict[str, Any]:
    input_path = Path(input_dir).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    message_catalog, file_summaries, errors = _scan_fit_folder(
        input_dir=input_path,
        recursive=recursive,
    )

    messages_dir = output_path / "messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    writers: Dict[str, csv.DictWriter] = {}
    handles: List[Any] = []

    try:
        for message_name in sorted(message_catalog):
            catalog = message_catalog[message_name]
            fieldnames = EXPORT_METADATA_COLUMNS + sorted(catalog.field_names)
            handle = (messages_dir / f"{safe_message_slug(message_name)}.csv").open(
                "w",
                newline="",
                encoding="utf-8",
            )
            handles.append(handle)
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writers[message_name] = writer

        for file_path in iter_fit_files(input_dir=input_path, recursive=recursive):
            try:
                fit_file = FitFile(str(file_path))
                message_indices: Counter = Counter()
                global_index = 0

                for message in fit_file.get_messages():
                    message_name = resolve_message_name(message)
                    global_index += 1
                    message_indices[message_name] += 1

                    values, _ = extract_message_values(message)
                    row = {
                        "source_file": file_path.name,
                        "source_path": str(file_path),
                        "message_name": message_name,
                        "message_number": getattr(message, "mesg_num", None),
                        "message_index": global_index,
                        "message_index_within_type": message_indices[message_name],
                    }
                    row.update(values)
                    writers[message_name].writerow(row)
            except Exception:
                continue
    finally:
        for handle in handles:
            handle.close()

    _write_file_summaries(output_path, file_summaries)
    _write_message_catalog(output_path, message_catalog)

    manifest = _build_manifest(
        input_dir=input_path,
        output_dir=output_path,
        message_catalog=message_catalog,
        file_summaries=file_summaries,
        errors=errors,
    )

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return manifest
