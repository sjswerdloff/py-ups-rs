"""Service provider for shared service instances."""

import logging

from pyupsrs.config import Config
from pyupsrs.domain.services import subscription_service as svc_subscription_service
from pyupsrs.domain.services import workitem_service as svc_workitem_service
from pyupsrs.storage.repositories import subscription_repository, workitem_repository
from pyupsrs.websocket.connection_manager import ConnectionManager
from pyupsrs.websocket.notification_service import NotificationService


class ServiceProvider:
    """Provider for shared service instances."""

    _instance = None

    @classmethod
    def get_instance(cls) -> "ServiceProvider":
        """
        Get or create the singleton instance of ServiceProvider.

        Returns:
            The singleton instance.

        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialize service provider."""
        self.logger = logging.getLogger("pyupsrs.services.provider")
        self.logger.info("Initializing shared service provider")

        # Initialize shared services
        self.connection_manager = ConnectionManager()
        self.notification_service = NotificationService(self.connection_manager)

        # Initialize repositories
        self.workitem_repo = workitem_repository.WorkItemRepository(database_uri=Config.database_uri)
        self.subscription_repo = subscription_repository.SubscriptionRepository(database_uri=Config.database_uri)

        # Initialize domain services
        self.workitem_service = svc_workitem_service.WorkItemService(
            workitem_repository=self.workitem_repo, notification_service=self.notification_service
        )
        self.subscription_service = svc_subscription_service.SubscriptionService(
            subscription_repository=self.subscription_repo
        )
