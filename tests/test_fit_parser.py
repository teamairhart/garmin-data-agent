import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.fit_parser import (
    build_file_summary_row,
    extract_message_values,
    normalize_value,
    safe_message_slug,
)


class FakeField:
    def __init__(self, name, value, def_num=None, units=None):
        self.name = name
        self.value = value
        self.def_num = def_num
        self.units = units


class FitParserTests(unittest.TestCase):
    def test_normalize_value_handles_complex_shapes(self):
        timestamp = datetime(2026, 3, 28, 21, 30, tzinfo=timezone.utc)

        self.assertEqual(normalize_value(timestamp), "2026-03-28T21:30:00+00:00")
        self.assertEqual(normalize_value(b"\x00\xff"), "00ff")
        self.assertEqual(normalize_value([1, 2, 3]), "[1, 2, 3]")
        self.assertEqual(normalize_value({"left": 42}), '{"left": 42}')

    def test_extract_message_values_preserves_metadata(self):
        message = [
            FakeField("power", 325, def_num=7, units="W"),
            FakeField("timestamp", datetime(2026, 3, 28, 21, 30, tzinfo=timezone.utc), def_num=253),
        ]

        values, metadata = extract_message_values(message)

        self.assertEqual(values["power"], 325)
        self.assertEqual(values["timestamp"], "2026-03-28T21:30:00+00:00")
        self.assertEqual(metadata["power"]["definition_number"], 7)
        self.assertEqual(metadata["power"]["units"], "W")
        self.assertEqual(metadata["timestamp"]["definition_number"], 253)

    def test_build_file_summary_row_uses_session_and_file_id_fields(self):
        row = build_file_summary_row(
            file_path=Path("/tmp/sample.fit"),
            message_counts=Counter({"record": 10, "session": 1}),
            session_data={
                "start_time": "2026-03-28T21:00:00+00:00",
                "sport": "cycling",
                "sub_sport": "road",
                "total_distance": 40234.5,
                "total_timer_time": 3800,
                "enhanced_avg_speed": 9.5,
                "avg_power": 247,
                "training_stress_score": 81.2,
            },
            file_id_data={
                "time_created": "2026-03-28T21:00:00+00:00",
                "type": "activity",
                "manufacturer": "garmin",
            },
        )

        self.assertEqual(row["source_file"], "sample.fit")
        self.assertEqual(row["total_messages"], 11)
        self.assertEqual(row["message_type_count"], 2)
        self.assertEqual(row["sport"], "cycling")
        self.assertEqual(row["avg_speed_mps"], 9.5)
        self.assertEqual(row["training_stress_score"], 81.2)

    def test_safe_message_slug_sanitizes_unfriendly_names(self):
        self.assertEqual(safe_message_slug("developer data/id"), "developer_data_id")


if __name__ == "__main__":
    unittest.main()
