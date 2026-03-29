#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.training_dataset import build_training_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Garmin ride summaries with Apple Health daily recovery data.",
    )
    parser.add_argument(
        "--garmin-file-summary",
        required=True,
        help="Path to Garmin file_summary.csv from the FIT export pipeline",
    )
    parser.add_argument(
        "--apple-daily-metrics",
        required=True,
        help="Path to Apple Health daily_metrics.csv from the Apple Health export pipeline",
    )
    parser.add_argument(
        "-o",
        "--output-path",
        default="exports/training_dataset/training_daily.csv",
        help="Output CSV path for the merged daily dataset",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    merged = build_training_dataset(
        garmin_file_summary_path=Path(args.garmin_file_summary),
        apple_daily_metrics_path=Path(args.apple_daily_metrics),
        output_path=Path(args.output_path),
    )

    print(
        json.dumps(
            {
                "rows": int(len(merged)),
                "columns": int(len(merged.columns)),
                "output_path": str(Path(args.output_path).expanduser().resolve()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
