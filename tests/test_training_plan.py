import unittest
from datetime import date
from pathlib import Path

from src.dashboard_data import build_dashboard_context
from src.training_plan import get_training_day, load_training_calendar


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TrainingPlanTests(unittest.TestCase):
    def test_training_calendar_has_expected_day(self):
        calendar = load_training_calendar(PROJECT_ROOT / "config" / "training_calendar.json")
        training_day = get_training_day(calendar, date(2026, 3, 29))

        self.assertIsNotNone(training_day)
        self.assertEqual(training_day.location, "Park City")
        self.assertEqual(training_day.headline, "Easy altitude endurance")
        self.assertGreater(len(training_day.prescriptions), 0)

    def test_dashboard_context_includes_today_and_upcoming(self):
        context = build_dashboard_context(today=date(2026, 3, 29))

        self.assertEqual(context["today"], "2026-03-29")
        self.assertIsNotNone(context["today_plan"])
        self.assertGreaterEqual(len(context["upcoming_plan"]), 1)
        self.assertGreaterEqual(len(context["race_cards"]), 1)


if __name__ == "__main__":
    unittest.main()
