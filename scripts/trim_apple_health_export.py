#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.apple_health_trim import trim_apple_health_export


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a trimmed Apple Health export that keeps only data on or after a cutoff date.",
    )
    parser.add_argument("source_dir", help="Directory containing export.xml")
    parser.add_argument("output_dir", help="Directory where the trimmed export will be written")
    parser.add_argument(
        "--cutoff-date",
        required=True,
        help="Keep only data on or after this date, formatted as YYYY-MM-DD",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = trim_apple_health_export(
        source_dir=Path(args.source_dir),
        output_dir=Path(args.output_dir),
        cutoff_date=args.cutoff_date,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
