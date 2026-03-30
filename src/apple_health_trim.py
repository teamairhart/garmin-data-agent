from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from xml.sax.saxutils import quoteattr

from .apple_health_parser import SLEEP_RECORD_TYPE, parse_apple_datetime, parse_cutoff_date, strip_namespace


TOP_LEVEL_COPY_TAGS = {
    "ExportDate",
    "Me",
    "Record",
    "Workout",
    "ActivitySummary",
    "ClinicalRecord",
    "Correlation",
    "WorkoutRoute",
}


def _activity_summary_date(attributes: Dict[str, Any]) -> Optional[date]:
    date_components = attributes.get("dateComponents")
    if date_components and re.match(r"^\d{4}-\d{2}-\d{2}$", str(date_components)):
        return datetime.strptime(str(date_components), "%Y-%m-%d").date()
    return None


def _element_anchor_date(tag: str, attributes: Dict[str, str]) -> Optional[date]:
    if tag == "ActivitySummary":
        return _activity_summary_date(attributes)

    start_dt = parse_apple_datetime(attributes.get("startDate"))
    end_dt = parse_apple_datetime(attributes.get("endDate"))
    creation_dt = parse_apple_datetime(attributes.get("creationDate"))

    if tag == "Record" and attributes.get("type") == SLEEP_RECORD_TYPE:
        anchor = end_dt or start_dt or creation_dt
    else:
        anchor = end_dt or start_dt or creation_dt

    return anchor.date() if anchor else None


def _keep_element(tag: str, attributes: Dict[str, str], cutoff_date: date) -> bool:
    if tag not in TOP_LEVEL_COPY_TAGS:
        return False

    if tag in {"ExportDate", "Me"}:
        return True

    if tag in {"Record", "Workout", "ActivitySummary", "ClinicalRecord", "Correlation", "WorkoutRoute"}:
        anchor_date = _element_anchor_date(tag, attributes)
        return bool(anchor_date and anchor_date >= cutoff_date)

    return False


def _copy_sidecar_tree(
    source_dir: Path,
    output_dir: Path,
    cutoff_date: date,
) -> Dict[str, int]:
    copied_counts = {"copied": 0, "skipped": 0}
    if not source_dir.exists():
        return copied_counts

    output_dir.mkdir(parents=True, exist_ok=True)

    for source_file in sorted(source_dir.glob("*")):
        if not source_file.is_file():
            continue

        match = re.search(r"(\d{4}-\d{2}-\d{2})", source_file.name)
        if match:
            file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            if file_date < cutoff_date:
                copied_counts["skipped"] += 1
                continue

        shutil.copy2(source_file, output_dir / source_file.name)
        copied_counts["copied"] += 1

    return copied_counts


def trim_apple_health_export(
    source_dir: str | Path,
    output_dir: str | Path,
    cutoff_date: Any,
) -> Dict[str, Any]:
    source_path = Path(source_dir).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    cutoff = parse_cutoff_date(cutoff_date)
    if cutoff is None:
        raise ValueError("cutoff_date is required")

    input_xml = source_path / "export.xml"
    if not input_xml.exists():
        raise FileNotFoundError(f"export.xml not found in {source_path}")

    output_path.mkdir(parents=True, exist_ok=True)
    output_xml = output_path / "export.xml"

    kept_counts: Counter = Counter()
    skipped_counts: Counter = Counter()
    root_tag: Optional[str] = None
    root_written = False

    context = ET.iterparse(input_xml, events=("start", "end"))
    with output_xml.open("w", encoding="utf-8") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')

        for event, element in context:
            tag = strip_namespace(element.tag)

            if event == "start" and not root_written:
                root_tag = tag
                attrs = " ".join(f"{key}={quoteattr(value)}" for key, value in element.attrib.items())
                handle.write(f"<{root_tag}{(' ' + attrs) if attrs else ''}>\n")
                root_written = True
                continue

            if event != "end" or tag == root_tag:
                continue

            if _keep_element(tag, element.attrib, cutoff):
                handle.write(ET.tostring(element, encoding="unicode"))
                handle.write("\n")
                kept_counts[tag] += 1
            else:
                skipped_counts[tag] += 1

            element.clear()

        if root_tag:
            handle.write(f"</{root_tag}>\n")

    route_counts = _copy_sidecar_tree(
        source_dir=source_path / "workout-routes",
        output_dir=output_path / "workout-routes",
        cutoff_date=cutoff,
    )
    ecg_counts = _copy_sidecar_tree(
        source_dir=source_path / "electrocardiograms",
        output_dir=output_path / "electrocardiograms",
        cutoff_date=cutoff,
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_path),
        "output_dir": str(output_path),
        "cutoff_date": cutoff.isoformat(),
        "kept_counts": dict(sorted(kept_counts.items())),
        "skipped_counts": dict(sorted(skipped_counts.items())),
        "workout_route_files": route_counts,
        "electrocardiogram_files": ecg_counts,
        "skipped_files": ["export_cda.xml"],
    }
    (output_path / "trim_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
