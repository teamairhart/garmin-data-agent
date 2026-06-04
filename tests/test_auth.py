import tempfile
import unittest
from pathlib import Path

from src import auth


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_database = auth.DATABASE
        auth.DATABASE = str(Path(self.tmpdir.name) / "users.db")
        auth.init_db()

    def tearDown(self):
        auth.DATABASE = self.original_database
        self.tmpdir.cleanup()

    def test_login_normalizes_email_case_and_whitespace(self):
        user_id = auth.create_user("  Jonathan@Example.COM  ", "correct-horse", " Jonathan ")

        self.assertIsNotNone(user_id)
        user = auth.verify_user("jonathan@example.com", "correct-horse")
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "jonathan@example.com")
        self.assertEqual(user["name"], "Jonathan")

        user = auth.verify_user("  JONATHAN@EXAMPLE.COM  ", "correct-horse")
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], user_id)

    def test_create_user_rejects_case_variant_duplicate(self):
        first_id = auth.create_user("jonathan@example.com", "correct-horse", "Jonathan")
        second_id = auth.create_user("JONATHAN@example.com", "different-password", "Jonathan 2")

        self.assertIsNotNone(first_id)
        self.assertIsNone(second_id)
        self.assertIsNone(auth.verify_user("jonathan@example.com", "different-password"))


if __name__ == "__main__":
    unittest.main()
