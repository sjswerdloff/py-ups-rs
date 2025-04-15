"""Subscription service."""
from pyupsrs.utils.class_logger import LoggerMixin
from pyupsrs.domain.models.ups import Subscription
from pyupsrs.storage.repositories.subscription_repository import SubscriptionRepository

class SubscriptionService(LoggerMixin):
    """Service for managing subscriptions."""

    def __init__(self,
                 subscription_repository:SubscriptionRepository) -> None:
        """
        Initialise the Subscription service.

        Args:
            subscription_repository (SubscriptionRepository): the storage backing for maintaining the subscriptions
        """
        self.subscription_repository = subscription_repository

    def create_subscription(self, subscription: Subscription) -> Subscription:
        return self.subscription_repository.create(subscription)

    def delete_subscription(self, workitem_uid: str, ae_title: str) -> bool:
        return self.subscription_repository.delete(workitem_uid, ae_title)

    def get_by_ae_title(self, ae_title: str) -> list[Subscription]:
        return self.subscription_repository.get_by_ae_title(ae_title)

    def get_by_workitem_uid(self, workitem_uid: str) -> list[Subscription]:
        return self.subscription_repository.get_by_workitem(workitem_uid)

    def suspend(self, workitem_uid:str, ae_title: str) -> bool:
        subscriptions_by_ae = self.subscription_repository.get_by_ae_title(ae_title)
        if subscription_to_suspend := next(
            (
                subscription
                for subscription in subscriptions_by_ae
                if subscription.ae_title == ae_title and subscription.workitem_uid == workitem_uid
            ),
            None,
        ):
            suspended_subscription = Subscription(workitem_uid=subscription_to_suspend.workitem_uid,
                                                  ae_title=subscription_to_suspend.ae_title,
                                                  deletion_lock=subscription_to_suspend.deletion_lock,
                                                  contact_uri=subscription_to_suspend.contact_uri,
                                                  filter=subscription_to_suspend.filter,
                                                  suspended=True)
            self.delete_subscription(subscription_to_suspend.workitem_uid, subscription_to_suspend.ae_title)
            self.create_subscription(suspended_subscription)
            return True
        else:
            return False
