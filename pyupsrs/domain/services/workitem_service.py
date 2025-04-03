"""Business logic for handling UPS workitems."""

import logging
import sys

from pyupsrs.domain.models.ups import WorkItem, WorkItemStatus
from pyupsrs.storage.repositories.workitem_repository import WorkItemRepository
from pyupsrs.utils.class_logger import LoggerMixin
from pyupsrs.websocket.notification_service import NotificationService


class WorkItemService(LoggerMixin):
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

    def update_workitem_status(self, uid: str, new_status: WorkItemStatus, transaction_uid: str) -> tuple[WorkItem, bool]:
        """
        Update a workitem's status.

        Args:
            uid: The UID of the workitem.
            new_status: The new status.
            transaction_uid: The UID that acts as a lock on a workitem that is already IN PROGRESS

        Returns:
            A tuple of (updated workitem, success).

        """
        try:
            # Retrieve the workitem
            workitem = self.workitem_repository.get_by_uid(uid)
            if not isinstance(workitem, WorkItem):
                workitem = WorkItem(ds=workitem)

            if workitem is None:
                return None, False

            current_status = None
            if hasattr(workitem.ds, "ProcedureStepState"):
                current_status = workitem.ds.ProcedureStepState
            else:
                return workitem, False

            if current_status not in ["SCHEDULED"] and (not transaction_uid or (workitem.transaction_uid != transaction_uid)):
                return workitem, False

            if current_status in ["COMPLETED", "CANCELED"]:
                return workitem, False

            self.logger.warning(f"Attempting to update status from {str(current_status)} to {str(new_status)}")
            # Update status
            workitem.update_procedure_step_status(new_status)
            if new_status == WorkItemStatus.IN_PROGRESS:
                workitem.transaction_uid = transaction_uid

            # Save changes
            updated_workitem = self.workitem_repository.update(workitem)

            # Send notification
            if self.notification_service:
                self.notification_service.notify_status_change(updated_workitem)
            else:
                self.logger.warning("Notification Service not initialized, no notifications will be sent.")
        except Exception as e:
            self.logger.error(f"Problem while updating workitem status: {e}")
            raise e
        return updated_workitem, True
