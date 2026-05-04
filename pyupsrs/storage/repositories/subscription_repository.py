"""Repository for accessing UPS subscriptions via SQLite persistence."""

from datetime import datetime
from typing import Any

from pydicom import Dataset

from pyupsrs.domain.models.ups import Subscription
from pyupsrs.storage.database import Database
from pyupsrs.utils.class_logger import LoggerMixin


class SubscriptionRepository(LoggerMixin):
    """Repository for UPS subscriptions backed by SQLite."""

    def __init__(self, database: Database) -> None:
        """
        Initialize the repository.

        Args:
            database: The Database instance for persistence.

        """
        self._db = database

    def create(self, subscription: Subscription) -> Subscription:
        """
        Create a new subscription.

        Args:
            subscription: The subscription to create.

        Returns:
            The created subscription.

        """
        self._discard_suspended_equivalent(subscription)
        row = self._subscription_to_row(subscription)
        self._db.execute(
            """INSERT OR REPLACE INTO subscriptions
               (workitem_uid, subscriber_uid, created_at, deletion_lock,
                contact_uri, filter_json, suspended)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                row["workitem_uid"],
                row["subscriber_uid"],
                row["created_at"],
                row["deletion_lock"],
                row["contact_uri"],
                row["filter_json"],
                row["suspended"],
            ),
        )
        return subscription

    def _discard_suspended_equivalent(self, subscription: Subscription) -> None:
        """Remove any existing suspended subscription for the same workitem/AE pair."""
        self.logger.warning(f"Checking for suspended equivalent for {subscription}; discarding any suspended match")
        self._db.execute(
            "DELETE FROM subscriptions WHERE workitem_uid = ? AND subscriber_uid = ? AND suspended = 1",
            (subscription.workitem_uid, subscription.ae_title),
        )

    def _fetch_subscriptions(self, sql: str, params: tuple) -> list[Subscription]:
        """
        Fetch subscriptions using sql and params, mapping each row to a Subscription.

        Args:
            sql: The SQL query to execute.
            params: The parameters to bind to the query.

        Returns:
            List of Subscription objects.

        """
        rows = self._db.fetch_all(sql, params)
        return [self._row_to_subscription(row) for row in rows]

    def get_by_workitem_and_ae_title(self, workitem_uid: str, ae_title: str) -> list[Subscription]:
        """
        Get subscriptions by workitem UID and AE title.

        Args:
            workitem_uid: The UID of the workitem.
            ae_title: The AE Title of the subscriber.

        Returns:
            List of matching subscriptions.

        """
        return self._fetch_subscriptions(
            "SELECT * FROM subscriptions WHERE workitem_uid = ? AND subscriber_uid = ?",
            (workitem_uid, ae_title),
        )

    def get_by_ae_title(self, ae_title: str) -> list[Subscription]:
        """
        Get all subscriptions for an AE title.

        Args:
            ae_title: The AE Title of the subscriber.

        Returns:
            List of matching subscriptions.

        """
        return self._fetch_subscriptions(
            "SELECT * FROM subscriptions WHERE subscriber_uid = ?",
            (ae_title,),
        )

    def get_by_workitem(self, workitem_uid: str) -> list[Subscription]:
        """
        Get all subscriptions for a workitem.

        Args:
            workitem_uid: The UID of the workitem.

        Returns:
            List of matching subscriptions.

        """
        return self._fetch_subscriptions(
            "SELECT * FROM subscriptions WHERE workitem_uid = ?",
            (workitem_uid,),
        )

    def delete(self, workitem_uid: str, ae_title: str) -> bool:
        """
        Delete a subscription.

        Args:
            workitem_uid: The UID of the workitem.
            ae_title: The AE Title of the subscriber.

        Returns:
            True if deleted, False otherwise.

        """
        existing = self._db.fetch_one(
            "SELECT * FROM subscriptions WHERE workitem_uid = ? AND subscriber_uid = ?",
            (workitem_uid, ae_title),
        )
        if existing is None:
            return False
        self._db.execute(
            "DELETE FROM subscriptions WHERE workitem_uid = ? AND subscriber_uid = ?",
            (workitem_uid, ae_title),
        )
        return True

    @staticmethod
    def _subscription_to_row(subscription: Subscription) -> dict[str, Any]:
        """Convert a Subscription to a dictionary for database storage."""
        filter_json = None
        if subscription.filter is not None:
            filter_json = subscription.filter.to_json()

        return {
            "workitem_uid": subscription.workitem_uid,
            "subscriber_uid": subscription.ae_title,
            "created_at": subscription.created_at.isoformat() if subscription.created_at else datetime.now().isoformat(),
            "deletion_lock": 1 if subscription.deletion_lock else 0,
            "contact_uri": subscription.contact_uri,
            "filter_json": filter_json,
            "suspended": 1 if subscription.suspended else 0,
        }

    @staticmethod
    def _row_to_subscription(row: dict[str, Any]) -> Subscription:
        """Reconstruct a Subscription from a database row."""
        filter_ds = None
        if row.get("filter_json"):
            filter_ds = Dataset.from_json(row["filter_json"])

        return Subscription(
            workitem_uid=row["workitem_uid"],
            ae_title=row["subscriber_uid"],
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(),
            deletion_lock=bool(row.get("deletion_lock", 0)),
            contact_uri=row.get("contact_uri"),
            filter=filter_ds,
            suspended=bool(row.get("suspended", 0)),
        )
