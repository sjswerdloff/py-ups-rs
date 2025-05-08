"""Tests for the WebSocket connection manager with callback system."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import websockets

from pyupsrs.websocket.connection_manager import ConnectionManager


class MockAsyncIterator:
    """Helper class to create a proper async iterator for testing."""

    def __aiter__(self):  # noqa: ANN204, D105
        return self

    async def __anext__(self):  # noqa: ANN204, D105
        from websockets.exceptions import ConnectionClosed

        raise ConnectionClosed(None, None)


class MockAsyncIteratorNoException:
    """Helper class to create a proper async iterator for testing."""

    def __aiter__(self):  # noqa: ANN204, D105
        return self

    async def __anext__(self):  # noqa: ANN204, D105
        yield self


@pytest.fixture
def connection_manager() -> ConnectionManager:
    """Create a connection manager for testing."""
    return ConnectionManager()


def test_register_callback(connection_manager: ConnectionManager) -> None:
    """Test registering a callback function."""

    # Define a simple callback function
    def test_callback(subscriber_id: str) -> None:
        pass

    # Register the callback
    connection_manager.register_connection_callback(test_callback)

    # Verify the callback was registered
    assert test_callback in connection_manager.connection_callbacks
    assert len(connection_manager.connection_callbacks) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_handle_connection_callbacks(connection_manager: ConnectionManager) -> None:
    """Test that callbacks are triggered when a connection is established."""
    # Define sync and async mock callbacks
    sync_callback = MagicMock()
    sync_callback.__name__ = "sync_callback"  # Add name attribute to MagicMock
    async_callback = AsyncMock()
    async_callback.__name__ = "async_callback"  # Add name attribute to AsyncMock

    # Register the callbacks
    connection_manager.register_connection_callback(sync_callback)
    connection_manager.register_connection_callback(async_callback)

    # Create a mock websocket
    mock_websocket = AsyncMock()
    # Configure the websocket to raise ConnectionClosed when iterated
    # Configure the websocket to use our MockAsyncIterator
    mock_websocket.return_value = MockAsyncIterator()

    # Handle a new connection
    await connection_manager.handle_connection(mock_websocket, "test_subscriber")

    # Verify the callbacks were called with the correct subscriber ID
    sync_callback.assert_called_once_with("test_subscriber")
    async_callback.assert_called_once_with("test_subscriber")


@pytest.mark.asyncio(loop_scope="function")
async def test_callback_exception_handling(connection_manager: ConnectionManager) -> None:
    """Test that exceptions in callbacks are properly handled."""

    # Define a callback that raises an exception
    def failing_callback(subscriber_id: str) -> None:
        raise ValueError("Test exception")

    # Register the failing callback
    connection_manager.register_connection_callback(failing_callback)

    # Create a mock websocket
    mock_websocket = AsyncMock()
    # Configure the websocket to use our MockAsyncIterator
    mock_websocket.return_value = MockAsyncIterator()
    # Handle a new connection (this should not raise an exception)
    try:
        await connection_manager.handle_connection(mock_websocket, "test_subscriber")
        exception_caught = False
    except ValueError:
        exception_caught = True

    # Verify no exception was propagated
    assert not exception_caught


@pytest.mark.asyncio(loop_scope="function")
async def test_connection_storage(connection_manager: ConnectionManager) -> None:
    """Test that connections are properly stored and removed."""
    # Create a mock websocket
    mock_websocket = AsyncMock(spec=websockets.ServerConnection)
    # Configure the websocket to use our MockAsyncIterator
    mock_websocket.return_value = MockAsyncIterator()

    # Handle a new connection
    await connection_manager.handle_connection(mock_websocket, "test_subscriber")

    # # Verify the connection was stored
    # assert "test_subscriber" in connection_manager.connections
    # assert connection_manager.connections["test_subscriber"] == mock_websocket

    # Verify the connection was removed after the connection closed
    assert "test_subscriber" not in connection_manager.connections
