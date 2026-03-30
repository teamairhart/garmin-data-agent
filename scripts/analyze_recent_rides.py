#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.recent_ride_analysis import build_recent_ride_analysis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze recent Garmin rides against the athlete profile and Dr. Testa zones.",
    )
    parser.add_argument(
        "--session-csv",
        default="exports/edge840_recent/messages/session.csv",
        help="Path to the Garmin session CSV",
    )
    parser.add_argument(
        "--record-csv",
        default="exports/edge840_recent/messages/record.csv",
        help="Path to the Garmin record CSV",
    )
    parser.add_argument(
        "--profile-path",
        default="config/athlete_profile.json",
        help="Path to the machine-readable athlete profile JSON",
    )
    parser.add_argument(
        "--start-date",
        default="2026-03-01",
        help="Only analyze rides on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "-o",
        "--output-path",
        default="exports/analysis/recent_ride_diagnostics.csv",
        help="Output CSV path for the ride diagnostics",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    diagnostics = build_recent_ride_analysis(
        session_csv_path=Path(args.session_csv),
        record_csv_path=Path(args.record_csv),
        profile_path=Path(args.profile_path),
        output_path=Path(args.output_path),
        start_date=args.start_date,
    )

    print(
        json.dumps(
            {
                "rows": int(len(diagnostics)),
                "output_path": str(Path(args.output_path).expanduser().resolve()),
                "start_date": args.start_date,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
