import csv
import tempfile
import unittest
from pathlib import Path

from src.apple_health_parser import export_apple_health_xml, parse_apple_datetime
from src.training_dataset import build_training_dataset


APPLE_XML_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
  <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="Apple Watch" unit="count/min" creationDate="2026-03-28 07:10:00 -0600" startDate="2026-03-28 07:00:00 -0600" endDate="2026-03-28 07:00:00 -0600" value="49"/>
  <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Apple Watch" unit="ms" creationDate="2026-03-28 07:10:00 -0600" startDate="2026-03-28 07:00:00 -0600" endDate="2026-03-28 07:00:00 -0600" value="78"/>
  <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" creationDate="2026-03-28 06:30:00 -0600" startDate="2026-03-27 22:30:00 -0600" endDate="2026-03-28 06:15:00 -0600" value="3"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeCycling" duration="3600" durationUnit="s" totalDistance="40200" totalDistanceUnit="m" totalEnergyBurned="950" totalEnergyBurnedUnit="Cal" sourceName="Apple Watch" creationDate="2026-03-28 12:15:00 -0600" startDate="2026-03-28 11:00:00 -0600" endDate="2026-03-28 12:00:00 -0600"/>
  <ActivitySummary dateComponents="2026-03-28" activeEnergyBurned="980" activeEnergyBurnedGoal="900" appleExerciseTime="75" appleExerciseTimeGoal="60" appleStandHours="12" appleStandHoursGoal="12"/>
</HealthData>
"""


class AppleHealthParserTests(unittest.TestCase):
    def test_parse_apple_datetime(self):
        parsed = parse_apple_datetime("2026-03-28 07:00:00 -0600")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2026-03-28T07:00:00-06:00")

    def test_export_and_merge_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            xml_path = base_path / "export.xml"
            xml_path.write_text(APPLE_XML_FIXTURE, encoding="utf-8")

            apple_output_dir = base_path / "apple_output"
            manifest = export_apple_health_xml(xml_path=xml_path, output_dir=apple_output_dir)

            self.assertEqual(manifest["record_type_count"], 3)
            self.assertEqual(manifest["workout_row_count"], 1)
            self.assertEqual(manifest["activity_summary_row_count"], 1)

            daily_metrics_path = apple_output_dir / "daily_metrics.csv"
            with daily_metrics_path.open() as handle:
                daily_rows = list(csv.DictReader(handle))
            self.assertEqual(len(daily_rows), 1)
            self.assertEqual(daily_rows[0]["date"], "2026-03-28")
            self.assertEqual(float(daily_rows[0]["sleep_asleep_seconds"]), 27900.0)
            self.assertEqual(float(daily_rows[0]["resting_heart_rate_avg"]), 49.0)

            garmin_summary_path = base_path / "file_summary.csv"
            garmin_summary_path.write_text(
                "\n".join(
                    [
                        "source_file,activity_time_created,start_time,total_distance_m,total_timer_time_s,avg_speed_mps,max_speed_mps,avg_power_w,max_power_w,normalized_power_w,threshold_power_w,intensity_factor,total_work_j,avg_heart_rate_bpm,max_heart_rate_bpm,total_ascent_m,total_descent_m,training_stress_score,total_training_effect,total_anaerobic_training_effect",
                        "ride.fit,2026-03-27T12:00:00-06:00,2026-03-27T12:00:00-06:00,40000,5400,8.5,15.2,250,620,272,300,0.9,1350000,150,180,450,450,82,3.8,1.5",
                        "ride2.fit,2026-03-28T11:00:00-06:00,2026-03-28T11:00:00-06:00,40200,3600,9.0,16.1,260,700,281,300,0.93,936000,152,185,510,510,88,4.1,1.7",
                    ]
                ),
                encoding="utf-8",
            )

            merged_output_path = base_path / "training_daily.csv"
            merged = build_training_dataset(
                garmin_file_summary_path=garmin_summary_path,
                apple_daily_metrics_path=daily_metrics_path,
                output_path=merged_output_path,
            )

            self.assertEqual(list(merged["date"]), ["2026-03-27", "2026-03-28"])
            self.assertEqual(float(merged.loc[1, "garmin_total_tss_prev_day"]), 82.0)
            self.assertEqual(float(merged.loc[1, "sleep_asleep_hours"]), 7.75)


if __name__ == "__main__":
    unittest.main()
