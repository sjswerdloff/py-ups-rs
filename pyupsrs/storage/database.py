"""Database connection management for UPS workitem and subscription persistence."""

import contextlib
import sqlite3
from collections.abc import Generator
from typing import Any


class Database:
    """Database connection manager for SQLite-backed UPS storage."""

    def __init__(self, uri: str) -> None:
        """
        Initialize the database connection.

        Args:
            uri: The database URI. Accepts:
                - Plain path: "ups.db", "/path/to/ups.db"
                - SQLite URI prefix: "sqlite:///ups.db", "sqlite:///path/to/ups.db"
                - In-memory: ":memory:"

        """
        self._db_path = self._parse_uri(uri)
        # For :memory: databases, keep a persistent connection since the DB
        # only exists for the lifetime of the connection.
        self._persistent_conn: sqlite3.Connection | None = None
        if self._db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row
        self._initialize_db()

    @staticmethod
    def _parse_uri(uri: str) -> str:
        """
        Parse a database URI into a path suitable for sqlite3.connect.

        Args:
            uri: The raw URI from configuration.

        Returns:
            A path string for sqlite3.connect.

        """
        if uri == ":memory:":
            return uri
        if uri.startswith("sqlite:///"):
            path = uri[len("sqlite:///"):]
            return path if path else "ups.db"
        return uri

    def _initialize_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workitems (
                    uid TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    dataset_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    transaction_uid TEXT,
                    scheduled_start_time TEXT,
                    scheduled_end_time TEXT,
                    patient_name TEXT,
                    patient_id TEXT,
                    accession_number TEXT,
                    procedure_step_type TEXT,
                    procedure_code TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    workitem_uid TEXT NOT NULL,
                    subscriber_uid TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    deletion_lock INTEGER NOT NULL DEFAULT 0,
                    contact_uri TEXT,
                    filter_json TEXT,
                    suspended INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (workitem_uid, subscriber_uid)
                )
            """)

            # Indexes for common query patterns
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_workitems_status
                ON workitems(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_workitems_patient_id
                ON workitems(patient_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_workitems_scheduled_start
                ON workitems(scheduled_start_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_workitem
                ON subscriptions(workitem_uid)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_subscriber
                ON subscriptions(subscriber_uid)
            """)

            conn.commit()

    @contextlib.contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection.

        For :memory: databases, returns the persistent connection.
        For file-backed databases, opens a new connection per operation.

        Yields:
            A database connection with Row factory enabled.

        """
        if self._persistent_conn is not None:
            yield self._persistent_conn
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        """
        Execute a write query (INSERT, UPDATE, DELETE).

        Args:
            query: The SQL query.
            params: The query parameters.

        """
        with self._get_connection() as conn:
            conn.execute(query, params or ())
            conn.commit()

    def fetch_one(self, query: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        """
        Fetch a single row.

        Args:
            query: The SQL query.
            params: The query parameters.

        Returns:
            The row as a dictionary, or None if not found.

        """
        with self._get_connection() as conn:
            cursor = conn.execute(query, params or ())
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
        with self._get_connection() as conn:
            cursor = conn.execute(query, params or ())
            return [dict(row) for row in cursor.fetchall()]
