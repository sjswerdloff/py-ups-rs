"""Business logic for handling UPS workitems."""

import logging
import sys

from pyupsrs.domain.models.ups import WorkItem, WorkItemStatus
from pyupsrs.storage.repositories.workitem_repository import WorkItemRepository
from pyupsrs.websocket.notification_service import NotificationService


class WorkItemService:
    """Service for managing UPS workitems."""

    def __init__(
        self,
        workitem_repository: WorkItemRepository,
        notification_service: NotificationService,
    ) -> None:
        """
        Initialize the WorkItemService.

        Args:
            workitem_repository: Repository for accessing workitems.
            notification_service: Service for sending notifications.

        """
        self.workitem_repository = workitem_repository
        self.notification_service = notification_service

        self.logger = logging.getLogger("pyupsrs.domain.services.workitem_service.WorkItemService")
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)

    def create_workitem(self, workitem: WorkItem) -> WorkItem:
        """
        Create a new workitem.

        Args:
            workitem: The workitem to create.

        Returns:
            The created workitem.

        """
        # Save to repository
        created_workitem = self.workitem_repository.create(workitem)

        # Send notification
        if self.notification_service:
            self.notification_service.notify_creation(created_workitem)
        else:
            self.logger.warning("Notification Service not injected, no notifications will be sent")

        return created_workitem

    def update_workitem_status(self, uid: str, new_status: WorkItemStatus) -> tuple[WorkItem, bool]:
        """
        Update a workitem's status.

        Args:
            uid: The UID of the workitem.
            new_status: The new status.

        Returns:
            A tuple of (updated workitem, success).

        """
        # Retrieve the workitem
        workitem = self.workitem_repository.get_by_uid(uid)
        if not workitem:
            return None, False

        # Update status
        workitem.update_status(new_status)

        # Save changes
        updated_workitem = self.workitem_repository.update(workitem)

        # Send notification
        self.notification_service.notify_status_change(updated_workitem)

        return updated_workitem, True
