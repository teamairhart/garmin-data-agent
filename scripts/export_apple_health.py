#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.apple_health_parser import export_apple_health_xml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Apple Health XML into analysis-ready CSVs and daily metrics.",
    )
    parser.add_argument("xml_path", help="Path to Apple Health export.xml")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="exports/apple_health",
        help="Directory where Apple Health CSV outputs will be written",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = export_apple_health_xml(
        xml_path=Path(args.xml_path),
        output_dir=Path(args.output_dir),
    )
    print(
        json.dumps(
            {
                "input_file": manifest["input_file"],
                "output_dir": manifest["output_dir"],
                "record_type_count": manifest["record_type_count"],
                "record_row_count": manifest["record_row_count"],
                "workout_row_count": manifest["workout_row_count"],
                "activity_summary_row_count": manifest["activity_summary_row_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
