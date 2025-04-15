"""Repository for accessing UPS subscriptions."""

from copy import deepcopy
from typing import Optional

from pyupsrs.domain.models.ups import Subscription

_local_store: set[Subscription] = set()


class SubscriptionRepository:
    """Repository for UPS subscriptions."""

    def __init__(self, database_uri: str) -> None:
        """
        Initialize the repository.

        Args:
            database_uri: The URI for the database.

        """
        self.database_uri = database_uri

    def create(self, subscription: Subscription) -> Subscription:
        """
        Create a new subscription.

        Args:
            subscription: The subscription to create.

        Returns:
            The created subscription.

        """
        # TODO: Implement database persistence
        _local_store.add(subscription)
        return subscription

    def get_by_ae_title(self,  ae_title: str) -> Optional[list[Subscription]]:
        """
        Get a subscription by workitem and ae title.

        Args:
            workitem_uid: The UID of the workitem.
            ae_title: The AE Title of the subscriber.

        Returns:
            The subscription, or None if not found.

        """
        # TODO: Implement database retrieval
        return [deepcopy(x) for x in _local_store if x.ae_title == ae_title]

    def get_by_workitem(self, workitem_uid: str) -> list[Subscription]:
        """
        Get all subscriptions for a workitem.

        Args:
            workitem_uid: The UID of the workitem.

        Returns:
            A list of subscriptions.

        """
        # TODO: Implement database retrieval
        return [deepcopy(x) for x in _local_store if x.workitem_uid == workitem_uid]

    def delete(self, workitem_uid: str, ae_title: str) -> bool:
        """
        Delete a subscription.

        Args:
            workitem_uid: The UID of the workitem.
            ae_title: The AE Title of the subscriber.

        Returns:
            True if deleted, False otherwise.

        """
        if subscription_to_delete := next(
            (
                subscription
                for subscription in _local_store
                if subscription.ae_title == ae_title and subscription.workitem_uid == workitem_uid
            ),
            None,
        ):
            _local_store.discard(subscription_to_delete)
            return True
        return False
