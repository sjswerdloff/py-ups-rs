"""WebSocket notification service for UPS events."""

import json
import logging

from pyupsrs.domain.models.ups import WorkItem
from pyupsrs.websocket.connection_manager import ConnectionManager


class NotificationService:
    """Service for sending notifications via WebSockets."""

    def __init__(self, connection_manager: ConnectionManager) -> None:
        """
        Initialize the NotificationService.

        Args:
            connection_manager: Manager for WebSocket connections.

        """
        self.connection_manager = connection_manager

    def notify_creation(self, workitem: WorkItem) -> None:
        """
        Send a notification for workitem creation.

        Args:
            workitem: The created workitem.

        """
        # TODO: Notification Message needs to be in UPS Event format
        # currently this is just a stand-in
        message = {
            "event_type": "creation",
            "workitem_uid": workitem.uid,
            "timestamp": workitem.created_at.isoformat(),
        }
        self._send_notification(workitem.uid, message)

    def notify_status_change(self, workitem: WorkItem) -> None:
        """
        Send a notification for workitem status change.

        Args:
            workitem: The updated workitem.

        """
        # TODO: Notification Message needs to be in UPS Event format
        # currently this is just a stand-in
        message = {
            "event_type": "status_change",
            "workitem_uid": workitem.uid,
            "new_status": workitem.status.value,
            "timestamp": workitem.updated_at.isoformat(),
        }
        self._send_notification(workitem.uid, message)

    def _send_notification(self, workitem_uid: str, message: dict) -> None:
        """
        Send a notification to all subscribers.

        Args:
            workitem_uid: The UID of the workitem.
            message: The message to send.

        """
        subscribers = self.connection_manager.get_subscribers(workitem_uid)
        self.logger.debug(f"Sending notification to {len(subscribers)} subscribers for {workitem_uid}")
        for subscriber_id in subscribers:
            try:
                self.connection_manager.send_message(subscriber_id, json.dumps(message))
            except Exception as e:
                self.logger.error(f"Failed to send notification: {e}")
