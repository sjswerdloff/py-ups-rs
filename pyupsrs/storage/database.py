"""Database connection management."""

import contextlib
import sqlite3
from collections.abc import Iterable
from typing import Any


class Database:
    """Database connection manager."""

    def __init__(self, uri: str) -> None:
        """
        Initialize the database connection.

        Args:
            uri: The database URI.

        """
        self.uri = uri
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create workitems table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workitems (
                    uid TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    scheduled_start_time TEXT,
                    scheduled_end_time TEXT,
                    patient_name TEXT,
                    patient_id TEXT,
                    accession_number TEXT,
                    procedure_step_type TEXT,
                    procedure_code TEXT
                )
            """)

            # Create subscriptions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    workitem_uid TEXT NOT NULL,
                    subscriber_uid TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    deletion_lock INTEGER NOT NULL,
                    contact_uri TEXT,
                    PRIMARY KEY (workitem_uid, subscriber_uid),
                    FOREIGN KEY (workitem_uid) REFERENCES workitems (uid)
                        ON DELETE CASCADE
                )
            """)

            conn.commit()

    @contextlib.contextmanager
    def _get_connection(self) -> Iterable[sqlite3.Connection]:
        """
        Get a database connection.

        Yields:
            A database connection.

        """
        conn = sqlite3.connect(self.uri)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> sqlite3.Cursor:
        """
        Execute a query.

        Args:
            query: The SQL query.
            params: The query parameters.

        Returns:
            The cursor.

        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            conn.commit()
            return cursor

    def fetch_one(self, query: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        """
        Fetch a single row.

        Args:
            query: The SQL query.
            params: The query parameters.

        Returns:
            The row as a dictionary, or None if not found.

        """
        cursor = self.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def fetch_all(self, query: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        """
        Fetch all rows.

        Args:
            query: The SQL query.
            params: The query parameters.

        Returns:
            The rows as a list of dictionaries.

        """
        cursor = self.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
