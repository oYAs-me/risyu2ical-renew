from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class CalendarStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calendars (
                    token TEXT PRIMARY KEY,
                    calendar_name TEXT NOT NULL,
                    ical BLOB NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, calendar_name: str, ical: bytes) -> str:
        for _ in range(5):
            token = secrets.token_urlsafe(24)
            try:
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO calendars(token, calendar_name, ical, created_at) VALUES (?, ?, ?, ?)",
                        (token, calendar_name, sqlite3.Binary(ical), datetime.now(timezone.utc).isoformat()),
                    )
                return token
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("カレンダートークンを発行できません")

    def get(self, token: str) -> tuple[str, bytes] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT calendar_name, ical FROM calendars WHERE token = ?", (token,)
            ).fetchone()
        return None if row is None else (str(row["calendar_name"]), bytes(row["ical"]))
