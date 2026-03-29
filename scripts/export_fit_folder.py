#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fit_parser import export_fit_folder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export every message type and discovered field from a folder of Garmin FIT files.",
    )
    parser.add_argument("input_dir", help="Folder containing .fit files")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="exports/latest",
        help="Directory where CSV and manifest outputs will be written",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the top level of the input directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = export_fit_folder(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        recursive=not args.no_recursive,
    )

    summary = {
        "input_dir": manifest["input_dir"],
        "output_dir": manifest["output_dir"],
        "total_fit_files": manifest["total_fit_files"],
        "successful_files": manifest["successful_files"],
        "failed_files": manifest["failed_files"],
        "message_type_count": manifest["message_type_count"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
