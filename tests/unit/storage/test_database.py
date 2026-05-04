"""Tests for Database class — connection management, URI parsing, migrations."""

from pathlib import Path

from pyupsrs.storage.database import SCHEMA_VERSION, Database


class TestUriParsing:
    """Contract: Database correctly parses various URI formats."""

    def test_memory_uri(self) -> None:
        """Verify that ':memory:' URI is stored as-is."""
        db = Database(":memory:")
        assert db._db_path == ":memory:"

    def test_sqlite_prefix_stripped(self) -> None:
        """Verify that 'sqlite:///' prefix is stripped from relative paths."""
        db = Database("sqlite:///test.db")
        assert db._db_path == "test.db"

    def test_sqlite_prefix_absolute_path(self) -> None:
        """Verify that 'sqlite:////' prefix is stripped for absolute paths."""
        db = Database("sqlite:////tmp/test.db")
        assert db._db_path == "/tmp/test.db"

    def test_sqlite_prefix_empty_defaults(self) -> None:
        """Verify that an empty sqlite URI defaults to 'ups.db'."""
        db = Database("sqlite:///")
        assert db._db_path == "ups.db"

    def test_plain_path_unchanged(self) -> None:
        """Verify that a plain path without prefix is stored unchanged."""
        db = Database("my_database.db")
        assert db._db_path == "my_database.db"


class TestSchemaInitialization:
    """Contract: Database creates expected tables and indexes on init."""

    def test_creates_workitems_table(self) -> None:
        """Verify that the workitems table exists after initialization."""
        db = Database(":memory:")
        row = db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workitems'"
        )
        assert row is not None

    def test_creates_subscriptions_table(self) -> None:
        """Verify that the subscriptions table exists after initialization."""
        db = Database(":memory:")
        row = db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'"
        )
        assert row is not None

    def test_creates_schema_version_table(self) -> None:
        """Verify that the schema_version table exists after initialization."""
        db = Database(":memory:")
        row = db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        assert row is not None

    def test_schema_version_recorded(self) -> None:
        """Verify that the current schema version is recorded in schema_version."""
        db = Database(":memory:")
        row = db.fetch_one("SELECT MAX(version) as version FROM schema_version")
        assert row["version"] == SCHEMA_VERSION

    def test_workitems_has_dataset_json_column(self) -> None:
        """Verify that the workitems table includes a dataset_json column."""
        db = Database(":memory:")
        row = db.fetch_one(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='workitems'"
        )
        assert "dataset_json" in row["sql"]

    def test_indexes_created(self) -> None:
        """Verify that all expected indexes are created on initialization."""
        db = Database(":memory:")
        rows = db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        index_names = {r["name"] for r in rows}
        assert "idx_workitems_status" in index_names
        assert "idx_workitems_patient_id" in index_names
        assert "idx_subscriptions_workitem" in index_names


class TestMigrations:
    """Contract: Migrations are applied correctly and idempotently."""

    def test_fresh_db_gets_all_migrations(self) -> None:
        """Verify that a fresh database receives all migrations."""
        db = Database(":memory:")
        row = db.fetch_one("SELECT MAX(version) as version FROM schema_version")
        assert row["version"] == SCHEMA_VERSION

    def test_existing_db_not_re_migrated(self, tmp_path: Path) -> None:
        """Verify that reopening a database does not duplicate migration entries."""
        db_path = str(tmp_path / "test.db")
        # First init
        db1 = Database(db_path)
        rows1 = db1.fetch_all("SELECT * FROM schema_version")
        # Second init (simulate restart)
        db2 = Database(db_path)
        rows2 = db2.fetch_all("SELECT * FROM schema_version")
        # Should have same number of version entries
        assert len(rows1) == len(rows2)

    def test_data_survives_restart(self, tmp_path: Path) -> None:
        """Verify that data written before restart is still readable after."""
        db_path = str(tmp_path / "persist.db")
        db1 = Database(db_path)
        db1.execute(
            "INSERT INTO workitems (uid, status, dataset_json, created_at) VALUES (?, ?, ?, ?)",
            ("1.2.3.4", "SCHEDULED", '{}', "2026-01-01T00:00:00"),
        )
        # Restart
        db2 = Database(db_path)
        row = db2.fetch_one("SELECT * FROM workitems WHERE uid = ?", ("1.2.3.4",))
        assert row is not None
        assert row["status"] == "SCHEDULED"


class TestConnectionManagement:
    """Contract: Connection behavior differs for memory vs file databases."""

    def test_memory_db_uses_persistent_connection(self) -> None:
        """Verify that an in-memory database holds a persistent connection."""
        db = Database(":memory:")
        assert db._persistent_conn is not None

    def test_file_db_has_no_persistent_connection(self, tmp_path: Path) -> None:
        """Verify that a file-based database does not hold a persistent connection."""
        db = Database(str(tmp_path / "test.db"))
        assert db._persistent_conn is None

    def test_execute_and_fetch(self) -> None:
        """Verify that executed inserts are retrievable via fetch_one."""
        db = Database(":memory:")
        db.execute(
            "INSERT INTO workitems (uid, status, dataset_json, created_at) VALUES (?, ?, ?, ?)",
            ("uid-1", "SCHEDULED", '{"test": true}', "2026-05-04T00:00:00"),
        )
        row = db.fetch_one("SELECT * FROM workitems WHERE uid = ?", ("uid-1",))
        assert row["uid"] == "uid-1"
        assert row["dataset_json"] == '{"test": true}'

    def test_fetch_all_returns_list(self) -> None:
        """Verify that fetch_all returns all inserted rows."""
        db = Database(":memory:")
        db.execute(
            "INSERT INTO workitems (uid, status, dataset_json, created_at) VALUES (?, ?, ?, ?)",
            ("uid-1", "SCHEDULED", '{}', "2026-01-01"),
        )
        db.execute(
            "INSERT INTO workitems (uid, status, dataset_json, created_at) VALUES (?, ?, ?, ?)",
            ("uid-2", "COMPLETED", '{}', "2026-01-02"),
        )
        rows = db.fetch_all("SELECT * FROM workitems")
        assert len(rows) == 2

    def test_fetch_one_returns_none_for_missing(self) -> None:
        """Verify that fetch_one returns None when no row matches."""
        db = Database(":memory:")
        row = db.fetch_one("SELECT * FROM workitems WHERE uid = ?", ("nonexistent",))
        assert row is None
