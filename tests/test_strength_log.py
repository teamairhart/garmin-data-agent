import tempfile
import unittest
from datetime import date
from pathlib import Path

from src import auth
from src.strength_log import (best_set, canonicalize, coerce_session, epley_e1rm, format_sets,
                              load_exercise_library, parse_workout_log)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TODAY_ENTRY = """---
description: log
---

# Workout Log

> [!info]- How to log
> **Session header:** `## YYYY-MM-DD · Session name · Location`

## 2026-09-10 · Freestyle Upper
- Bench press: 135 x 10, 10, 8, 5
- Incline press (Hammer Strength): 35 x 15; 45 x 8, 9
- Lat pulldown (wide grip): 143 x 10, 10, 8; 120 x 10
- Hanging knee raise: bw x 15, 20, 10
- Kettlebell row: 35 x 10; 53 x 10, 10
Notes: First gym session in a long while. Baseline: bench e1RM ≈ 180 lb (135 x 10).
"""


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.lib = load_exercise_library()

    def test_today_entry_parses(self):
        sessions = parse_workout_log(TODAY_ENTRY, self.lib)
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s.session_date, "2026-09-10")
        self.assertEqual(s.title, "Freestyle Upper")
        self.assertIsNone(s.location)
        self.assertEqual([e.canonical for e in s.exercises],
                         ["Bench press", "Incline press (Hammer Strength)", "Lat pulldown (wide grip)",
                          "Hanging knee raise", "Kettlebell row"])
        self.assertTrue(all(e.known for e in s.exercises))
        bench = s.exercises[0]
        self.assertEqual([x.reps for x in bench.sets], [10, 10, 8, 5])
        self.assertEqual([x.load_lb for x in bench.sets], [135.0] * 4)
        incline = s.exercises[1]
        self.assertEqual([(x.load_lb, x.reps) for x in incline.sets], [(35.0, 15), (45.0, 8), (45.0, 9)])
        knee = s.exercises[3]
        self.assertEqual([x.load_kind for x in knee.sets], ["bw"] * 3)
        self.assertEqual(knee.category, "core")
        self.assertTrue(s.notes.startswith("First gym session"))
        self.assertEqual(s.warnings, [])
        self.assertEqual(s.session_type, "strength")

    def test_header_variants_and_meta_line(self):
        text = ("## 2026-09-12 - Lower - MEM\n"
                "bw: 198.5, time: 52 · rpe: 7\n"
                "- Trap-bar deadlift: 155# x 12, 12, 12 @7\n"
                "- Plank: bw x 45s, 1:00, 30s\n"
                "- Weird machine thing: 90 x 10\n"
                "random line that should be ignored\n"
                "Notes: back felt fine\n"
                "second notes line\n")
        s = parse_workout_log(text, self.lib)[0]
        self.assertEqual((s.title, s.location), ("Lower", "MEM"))
        self.assertEqual((s.bodyweight, s.duration_minutes, s.rpe), (198.5, 52, 7.0))
        tb = s.exercises[0]
        self.assertEqual(tb.canonical, "Trap-bar deadlift")
        self.assertEqual([x.rpe for x in tb.sets], [7.0, 7.0, 7.0])    # segment RPE applies to all
        plank = s.exercises[1]
        self.assertEqual([x.duration_s for x in plank.sets], [45, 60, 30])
        self.assertFalse(s.exercises[2].known)
        self.assertEqual(s.exercises[2].canonical, "Weird machine thing")
        self.assertEqual(s.notes, "back felt fine\nsecond notes line")
        self.assertTrue(any("ignored" in w for w in s.warnings))
        self.assertTrue(any("unknown exercise" in w for w in s.warnings))

    def test_amrap_per_set_rpe_bw_added_and_kg(self):
        text = ("## 2027-02-03 · Upper\n"
                "- Bench: 225 x 5, 5, 5+ @8.5\n"
                "- Pull-ups: bw+25 x 6@8, 5@9\n"
                "- Goblet squat: 24kg x 10\n"
                "- Dips: bw-30 x 8\n")
        s = parse_workout_log(text, self.lib)[0]
        bench = s.exercises[0]
        self.assertEqual(bench.canonical, "Bench press")
        self.assertEqual([x.is_amrap for x in bench.sets], [False, False, True])
        self.assertEqual([x.rpe for x in bench.sets], [8.5, 8.5, 8.5])
        pu = s.exercises[1]
        self.assertEqual(pu.canonical, "Pull-up")
        self.assertEqual([(x.load_kind, x.added_lb, x.reps, x.rpe) for x in pu.sets],
                         [("bw", 25.0, 6, 8.0), ("bw", 25.0, 5, 9.0)])
        self.assertAlmostEqual(s.exercises[2].sets[0].load_lb, 52.9, places=1)
        self.assertEqual(s.exercises[3].sets[0].added_lb, -30.0)

    def test_multiple_sessions_document_order_and_core_type(self):
        text = ("## 2026-09-14 · Upper A · PC\n- Bench press: 140 x 8, 8, 8\n\n"
                "## 2026-09-13 · Big 3\n- Curl-up: bw x 10, 10\n- Bird dog: bw x 10, 10\n")
        sessions = parse_workout_log(text, self.lib)
        self.assertEqual([s.session_date for s in sessions], ["2026-09-14", "2026-09-13"])
        self.assertEqual(sessions[1].session_type, "core")

    def test_canonicalize_aliases(self):
        self.assertEqual(canonicalize("KB rows", self.lib)[0], "Kettlebell row")
        self.assertEqual(canonicalize("Wide Lat pulldown", self.lib)[0], "Lat pulldown (wide grip)")
        self.assertEqual(canonicalize("Hanging Knee ups", self.lib)[0], "Hanging knee raise")
        self.assertEqual(canonicalize("hex bar deadlift", self.lib)[0], "Trap-bar deadlift")
        self.assertEqual(canonicalize("Incline hammer strength", self.lib)[0], "Incline press (Hammer Strength)")
        self.assertEqual(canonicalize("Some new thing (cable)", self.lib), ("Some new thing (cable)", "other", False))

    def test_epley_and_best_set_and_format(self):
        self.assertEqual(epley_e1rm(135, 10), 180.0)
        self.assertEqual(epley_e1rm(315, 1), 315.0)
        self.assertEqual(epley_e1rm(225, 12), 315.0)
        self.assertIsNone(epley_e1rm(None, 5))
        s = parse_workout_log(TODAY_ENTRY, self.lib)[0]
        self.assertEqual(best_set(s.exercises[0].sets)["e1rm"], 180.0)
        self.assertIsNone(best_set(s.exercises[3].sets))          # bodyweight: no e1RM
        self.assertEqual(format_sets([vars(x) for x in s.exercises[1].sets]), "35 x 15; 45 x 8, 9")
        self.assertEqual(format_sets([vars(x) for x in s.exercises[3].sets]), "bw x 15, 20, 10")

    def test_coerce_session_roundtrip_and_validation(self):
        s = parse_workout_log(TODAY_ENTRY, self.lib)[0]
        back = coerce_session(s.to_dict(), self.lib)
        self.assertEqual(back.title, s.title)
        self.assertEqual(len(back.exercises), 5)
        self.assertEqual(back.exercises[0].sets[0].load_lb, 135.0)
        with self.assertRaises(ValueError):
            coerce_session({"session_date": "not-a-date", "title": "x"}, self.lib)


class StorageAndPageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_database = auth.DATABASE
        auth.DATABASE = str(Path(self.tmpdir.name) / "users.db")
        import app as app_module
        self.app_module = app_module
        auth.init_db()
        from src.training_log import init_training_tables, init_strength_columns
        init_training_tables()
        init_strength_columns()
        auth.create_user("strength@example.com", "pw", "Tester")
        self.client = app_module.app.test_client()
        self.client.post("/auth/login", data={"email": "strength@example.com", "password": "pw"})

    def tearDown(self):
        auth.DATABASE = self.original_database
        self.tmpdir.cleanup()

    def test_api_upsert_is_idempotent_and_page_renders(self):
        r = self.client.post("/strength/sessions", json={"text": TODAY_ENTRY})
        self.assertEqual(r.status_code, 200, r.data)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["results"][0]["created"])
        self.assertEqual(body["results"][0]["sets"], 17)
        # re-post -> replaced, not duplicated
        r = self.client.post("/strength/sessions", json={"text": TODAY_ENTRY.replace("135 x 10, 10, 8, 5", "140 x 10, 10, 8")})
        self.assertFalse(r.get_json()["results"][0]["created"])
        listing = self.client.get("/strength/sessions").get_json()["sessions"]
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["exercises"][0]["sets_text"], "140 x 10, 10, 8")
        self.assertEqual(listing[0]["exercises"][0]["best"]["e1rm"], 186.7)
        page = self.client.get("/strength")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Freestyle Upper", html)
        self.assertIn("Bench ladder", html)
        self.assertIn("Transition", html)   # phase name from the plan JSON

    def test_form_post_and_pr_flags(self):
        self.client.post("/strength/log", data={"text": "## 2026-09-10 · Upper A\n- Bench press: 135 x 10\n"})
        self.client.post("/strength/log", data={"text": "## 2026-09-14 · Upper A\n- Bench press: 145 x 10\n"})
        from src.training_log import list_gym_sessions, strength_summary
        user_id = auth.verify_user("strength@example.com", "pw")["id"]
        sessions = list_gym_sessions(user_id)
        self.assertEqual([s["session_date"] for s in sessions], ["2026-09-14", "2026-09-10"])
        self.assertTrue(sessions[0]["exercises"][0]["pr"])
        self.assertTrue(sessions[1]["exercises"][0]["first"])
        summary = strength_summary(user_id, date(2026, 9, 15), sessions=sessions)
        self.assertEqual(summary["bench"]["best_e1rm"], 193.3)
        self.assertEqual(summary["week"]["gym_sessions"], 1)

    def test_login_required(self):
        anon = self.app_module.app.test_client()
        self.assertEqual(anon.post("/strength/sessions", json={"text": TODAY_ENTRY}).status_code, 401)
        self.assertEqual(anon.get("/strength").status_code, 302)


if __name__ == "__main__":
    unittest.main()
