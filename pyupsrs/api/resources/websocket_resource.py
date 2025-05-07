"""WebSocket resource for Falcon ASGI."""

import logging

import falcon.asgi

from pyupsrs.websocket.connection_manager import ConnectionManager


class WebSocketResource:
    """Resource for handling WebSocket connections."""

    def __init__(self, connection_manager: ConnectionManager) -> None:
        """
        Initialize the WebSocket resource.

        Args:
            connection_manager: Manager for WebSocket connections.

        """
        self.connection_manager = connection_manager
        self.logger = logging.getLogger("pyupsrs.websocket.resource")

    async def on_websocket(self, req: falcon.asgi.Request, ws: falcon.asgi.WebSocket, subscriber_id: str) -> None:
        """
        Handle WebSocket connections.

        Args:
            req: The request object.
            ws: The WebSocket connection.
            subscriber_id: The ID of the subscriber (from URL).

        """
        self.logger.info(f"WebSocket connection requested for subscriber {subscriber_id}")

        try:
            # Accept the connection
            await ws.accept()

            # Wrap Falcon's WebSocket to make it compatible with our ConnectionManager
            adapter = FalconWebSocketAdapter(ws)
            await self.connection_manager.handle_connection(adapter, subscriber_id)
        except Exception as e:
            self.logger.error(f"Error handling WebSocket connection: {e}")


class FalconWebSocketAdapter:
    """Adapter to make Falcon's WebSocket compatible with websockets.ServerConnection."""

    def __init__(self, ws: falcon.asgi.WebSocket) -> None:
        """
        Initialize the adapter.

        Args:
            ws: The Falcon WebSocket.

        """
        self.ws = ws
        self.logger = logging.getLogger("pyupsrs.websocket.adapter")

    async def send(self, message: str) -> None:
        """
        Send a message through the WebSocket.

        Args:
            message: The message to send.

        """
        try:
            await self.ws.send_text(message)
        except Exception as e:
            self.logger.error(f"Error sending message: {e}")
            raise

    async def __aiter__(self):  # noqa: ANN204
        """
        Iterate over incoming messages.

        Returns:
            An async iterator yielding messages.

        """
        while True:
            try:
                msg = await self.ws.receive_text()
                yield msg
            except falcon.WebSocketDisconnected as e_disconnect:
                self.logger.warning(f"WebSocket disconnected: {e_disconnect}")
                break
            except Exception as e:
                self.logger.error(f"Error receiving message: {e}")
                break
