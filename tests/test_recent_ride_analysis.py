import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.recent_ride_analysis import build_recent_ride_analysis


class RecentRideAnalysisTests(unittest.TestCase):
    def test_build_recent_ride_analysis_computes_zone_and_climb_metrics(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            profile_path = tmp_path / "profile.json"
            session_path = tmp_path / "session.csv"
            record_path = tmp_path / "record.csv"
            output_path = tmp_path / "analysis.csv"

            profile_path.write_text(
                json.dumps(
                    {
                        "lab_profiles": [
                            {
                                "training_zones": [
                                    {
                                        "name": "long_endurance",
                                        "power_w_min": 130,
                                        "power_w_max": 170,
                                    },
                                    {
                                        "name": "medium_endurance",
                                        "power_w_min": 190,
                                        "power_w_max": 220,
                                    },
                                    {
                                        "name": "threshold_flats",
                                        "power_w_min": 230,
                                        "power_w_max": 250,
                                        "heart_rate_bpm_min": 153,
                                        "heart_rate_bpm_max": 158,
                                    },
                                    {
                                        "name": "threshold_climbing",
                                        "power_w_min": 240,
                                        "power_w_max": 260,
                                        "heart_rate_bpm_min": 156,
                                        "heart_rate_bpm_max": 161,
                                    },
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            pd.DataFrame(
                [
                    {
                        "source_file": "ride.fit",
                        "start_time": "2026-03-28T10:00:00",
                        "start_position_lat": int(35.1 * (2**31) / 180),
                        "start_position_long": int(-90.0 * (2**31) / 180),
                        "total_timer_time": 19,
                        "total_distance": 190,
                        "total_ascent": 5,
                        "avg_power": 210,
                        "normalized_power": 240,
                        "avg_heart_rate": 154,
                        "max_heart_rate": 161,
                        "avg_cadence": 88,
                    }
                ]
            ).to_csv(session_path, index=False)

            base_time = pd.Timestamp("2026-03-28T10:00:00")
            records = []
            for second in range(20):
                climbing = second < 12
                records.append(
                    {
                        "source_file": "ride.fit",
                        "timestamp": (base_time + pd.Timedelta(seconds=second)).isoformat(),
                        "power": 245 if climbing else 150,
                        "heart_rate": 158 if climbing else 130,
                        "cadence": 88 if climbing else 90,
                        "distance": second * 10,
                        "enhanced_altitude": second * 0.5 if climbing else 6.0,
                    }
                )
            pd.DataFrame(records).to_csv(record_path, index=False)

            diagnostics = build_recent_ride_analysis(
                session_csv_path=session_path,
                record_csv_path=record_path,
                profile_path=profile_path,
                output_path=output_path,
                start_date="2026-03-01",
            )

            self.assertEqual(len(diagnostics), 1)
            row = diagnostics.iloc[0]
            self.assertEqual(row["location_context"], "memphis_region")
            self.assertGreater(row["time_threshold_flats_power_min"], 0)
            self.assertGreater(row["time_threshold_climbing_power_min"], 0)
            self.assertGreater(row["climb_minutes_ge_3pct"], 0)
            self.assertGreater(row["climb_avg_cadence_rpm"], 80)
            self.assertGreater(row["climb_cadence_85_95_pct"], 0.5)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
