"""Service provider for shared service instances."""

import logging

from pyupsrs.config import get_config
from pyupsrs.domain.services import subscription_service as svc_subscription_service
from pyupsrs.domain.services import workitem_service as svc_workitem_service
from pyupsrs.storage.database import Database
from pyupsrs.storage.repositories.subscription_repository import SubscriptionRepository
from pyupsrs.storage.repositories.workitem_repository import WorkItemRepository
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

        # Initialize database and repositories
        config = get_config()
        self.database = Database(config.database_uri)
        self.workitem_repo = WorkItemRepository(database=self.database)
        self.subscription_repo = SubscriptionRepository(database=self.database)

        # Initialize domain services
        self.workitem_service = svc_workitem_service.WorkItemService(
            workitem_repository=self.workitem_repo, notification_service=self.notification_service
        )
        self.subscription_service = svc_subscription_service.SubscriptionService(
            subscription_repository=self.subscription_repo
        )
