from __future__ import annotations

import contextlib
from typing import Generator
import psycopg
from psycopg.rows import dict_row

from engines.shared.config import settings


@contextlib.contextmanager
def get_db_cursor() -> Generator[psycopg.Cursor, None, None]:
    """Provides a thread-safe database connection and cursor for API endpoints."""
    url = settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not configured.")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            yield cur


def check_db_health() -> dict[str, str | bool]:
    """Checks database connectivity and server version without exposing credentials."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT current_database(), version();")
            row = cur.fetchone()
            if row:
                db_name = row["current_database"]
                raw_ver = row["version"]
                # Extract clean version, e.g. "PostgreSQL 18.6"
                ver = raw_ver.split(",")[0] if "," in raw_ver else raw_ver.split(" on ")[0]
                return {
                    "database_connected": True,
                    "database_name": db_name,
                    "database_version": ver,
                }
            return {"database_connected": False, "database_name": "unknown", "database_version": "unknown"}
    except Exception as e:
        return {
            "database_connected": False,
            "database_name": "unknown",
            "database_version": "unknown",
            "error": str(e),
        }

