"""Manager for WebSocket connections."""

import logging

import websockets


class ConnectionManager:
    """Manager for WebSocket connections."""

    def __init__(self) -> None:
        """Initialize the ConnectionManager."""
        self.connections: dict[str, websockets.WebSocketServerProtocol] = {}
        self.subscriptions: dict[str, set[str]] = {}  # workitem_uid -> set of subscriber_ids
        self.subscriber_to_workitems: dict[str, set[str]] = {}  # subscriber_id -> set of workitem_uids
        self.logger = logging.getLogger("pyupsrs.websocket")

    async def handle_connection(self, websocket: websockets.WebSocketServerProtocol, subscriber_id: str) -> None:
        """
        Handle a new WebSocket connection.

        Args:
            websocket: The WebSocket connection.
            subscriber_id: The ID of the subscriber.

        """
        self.connections[subscriber_id] = websocket
        self.logger.info(f"New connection from subscriber {subscriber_id}")

        try:
            # Keep the connection alive
            async for _message in websocket:
                # Process incoming messages if needed
                pass
        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"Connection closed from subscriber {subscriber_id}")
        finally:
            # Clean up when the connection is closed
            self._remove_connection(subscriber_id)

    def subscribe(self, subscriber_id: str, workitem_uid: str) -> None:
        """
        Subscribe to a workitem.

        Args:
            subscriber_id: The ID of the subscriber.
            workitem_uid: The UID of the workitem.

        """
        if workitem_uid not in self.subscriptions:
            self.subscriptions[workitem_uid] = set()
        self.subscriptions[workitem_uid].add(subscriber_id)

        if subscriber_id not in self.subscriber_to_workitems:
            self.subscriber_to_workitems[subscriber_id] = set()
        self.subscriber_to_workitems[subscriber_id].add(workitem_uid)

        self.logger.debug(f"Subscriber {subscriber_id} subscribed to {workitem_uid}")

    def unsubscribe(self, subscriber_id: str, workitem_uid: str) -> None:
        """
        Unsubscribe from a workitem.

        Args:
            subscriber_id: The ID of the subscriber.
            workitem_uid: The UID of the workitem.

        """
        if workitem_uid in self.subscriptions:
            self.subscriptions[workitem_uid].discard(subscriber_id)

        if subscriber_id in self.subscriber_to_workitems:
            self.subscriber_to_workitems[subscriber_id].discard(workitem_uid)

        self.logger.debug(f"Subscriber {subscriber_id} unsubscribed from {workitem_uid}")

    def get_subscribers(self, workitem_uid: str) -> set[str]:
        """
        Get all subscribers for a workitem.

        Args:
            workitem_uid: The UID of the workitem.

        Returns:
            A set of subscriber IDs.

        """
        return self.subscriptions.get(workitem_uid, set())

    async def send_message(self, subscriber_id: str, message: str) -> bool:
        """
        Send a message to a subscriber.

        Args:
            subscriber_id: The ID of the subscriber.
            message: The message to send.

        Returns:
            True if the message was sent, False otherwise.

        """
        websocket = self.connections.get(subscriber_id)
        if not websocket:
            return False

        try:
            await websocket.send(message)
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message to {subscriber_id}: {e}")
            return False

    def _remove_connection(self, subscriber_id: str) -> None:
        """
        Remove a connection and its subscriptions.

        Args:
            subscriber_id: The ID of the subscriber.

        """
        # Remove from connections
        if subscriber_id in self.connections:
            del self.connections[subscriber_id]

        # Remove from subscriptions
        workitem_uids = self.subscriber_to_workitems.get(subscriber_id, set())
        for workitem_uid in workitem_uids:
            if workitem_uid in self.subscriptions:
                self.subscriptions[workitem_uid].discard(subscriber_id)

        # Remove from subscriber_to_workitems
        if subscriber_id in self.subscriber_to_workitems:
            del self.subscriber_to_workitems[subscriber_id]
