#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash


def normalize_email(email: str) -> str:
    return email.strip().lower()


def ensure_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def prompt_password() -> str:
    password = getpass.getpass("New password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match.")
    if len(password) < 6:
        raise SystemExit("Password must be at least 6 characters.")
    return password


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset or create a Garmin Data Agent user password.")
    parser.add_argument("email", help="Account email address")
    parser.add_argument("--name", help="Display name to use if the account must be created")
    parser.add_argument(
        "--database",
        default=os.environ.get("DATABASE_PATH", "users.db"),
        help="SQLite database path. Defaults to DATABASE_PATH or users.db.",
    )
    args = parser.parse_args()

    email = normalize_email(args.email)
    name = (args.name or email.split("@", 1)[0]).strip()
    password_hash = generate_password_hash(prompt_password())

    database_path = Path(args.database).expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(database_path)
    try:
        ensure_users_table(conn)
        cursor = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (email,))
        row = cursor.fetchone()
        if row:
            conn.execute(
                "UPDATE users SET email = ?, password_hash = ?, name = COALESCE(NULLIF(name, ''), ?) WHERE id = ?",
                (email, password_hash, name, row[0]),
            )
            action = "Updated"
            user_id = row[0]
        else:
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
                (email, password_hash, name),
            )
            action = "Created"
            user_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    print(f"{action} user {user_id} in {database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
