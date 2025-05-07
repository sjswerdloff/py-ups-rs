"""Subscription service."""

from pyupsrs.domain.models.ups import Subscription
from pyupsrs.domain.services.service_provider import ServiceProvider
from pyupsrs.storage.repositories.subscription_repository import SubscriptionRepository
from pyupsrs.utils.class_logger import LoggerMixin


class SubscriptionService(LoggerMixin):
    """Service for managing subscriptions."""

    def __init__(self, subscription_repository: SubscriptionRepository) -> None:
        """
        Initialise the Subscription service.

        Args:
            subscription_repository (SubscriptionRepository): the storage backing for maintaining the subscriptions

        """
        self.subscription_repository = subscription_repository

    def create_subscription(self, subscription: Subscription) -> Subscription:
        """Cache Subscription in Connection Manager and Persist in repository."""
        ServiceProvider.get_instance().connection_manager.subscribe(subscription.ae_title, subscription.workitem_uid)
        return self.subscription_repository.create(subscription)

    def delete_subscription(self, workitem_uid: str, ae_title: str) -> bool:
        """Remove subscription from Connection Manager cache and delete from repository."""
        ServiceProvider.get_instance().connection_manager.unsubscribe(ae_title, workitem_uid)
        return self.subscription_repository.delete(workitem_uid, ae_title)

    def get_by_ae_title(self, ae_title: str) -> list[Subscription]:
        """Get Subscription list by AE Title."""
        return self.subscription_repository.get_by_ae_title(ae_title)

    def get_by_workitem_uid(self, workitem_uid: str) -> list[Subscription]:
        """Get Subscription list by workitem UID, which can be specific, GLOBAL or FILTERED."""
        return self.subscription_repository.get_by_workitem(workitem_uid)

    def suspend(self, workitem_uid: str, ae_title: str) -> bool:
        """Suspend the subscription."""
        subscriptions_by_ae = self.subscription_repository.get_by_ae_title(ae_title)
        if subscription_to_suspend := next(
            (
                subscription
                for subscription in subscriptions_by_ae
                if subscription.ae_title == ae_title and subscription.workitem_uid == workitem_uid
            ),
            None,
        ):
            suspended_subscription = Subscription(
                workitem_uid=subscription_to_suspend.workitem_uid,
                ae_title=subscription_to_suspend.ae_title,
                deletion_lock=subscription_to_suspend.deletion_lock,
                contact_uri=subscription_to_suspend.contact_uri,
                filter=subscription_to_suspend.filter,
                suspended=True,
            )
            ServiceProvider.get_instance().connection_manager.unsubscribe(ae_title, workitem_uid)  # equivalent to suspend
            self.logger.warning(f"Suspended connection manager subscription for {ae_title} to {workitem_uid}")
            self.delete_subscription(subscription_to_suspend.workitem_uid, subscription_to_suspend.ae_title)
            self.logger.warning(f"Deleted SubscriptionService subscription for {ae_title} to {workitem_uid}")
            self.create_subscription(suspended_subscription)
            return True
        else:
            self.logger.warning(f"No subscription found for {ae_title} to {workitem_uid}")
            return False
