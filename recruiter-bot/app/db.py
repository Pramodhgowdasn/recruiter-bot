"""SQLite connection handling. Plain `sqlite3` from the standard library:
no ORM, no query builder. Every statement in this project is hand-written SQL."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def database_path() -> str:
    return os.environ.get("RECRUITER_BOT_DB", "recruiter_bot.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite leaves FK enforcement off by default
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
