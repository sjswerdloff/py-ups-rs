"""Tests for the notification service with pending notification queue."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydicom import Dataset

import pyupsrs.domain.services.service_provider as service_provider
from pyupsrs.domain.models.ups import FILTERED_SUBSCRIPTION_UID, GLOBAL_SUBSCRIPTION_UID, Subscription, WorkItem
from pyupsrs.websocket.connection_manager import ConnectionManager
from pyupsrs.websocket.notification_service import NotificationService, create_ups_state_report


@pytest.fixture
def connection_manager() -> ConnectionManager:
    """Create a connection manager for testing."""
    return MagicMock(spec=ConnectionManager)


@pytest.fixture
def notification_service(connection_manager: ConnectionManager) -> NotificationService:
    """Create a notification service for testing."""
    return NotificationService(connection_manager)


@pytest.fixture
def sample_workitem() -> WorkItem:
    """Create a sample workitem for testing."""
    ds = Dataset()
    ds.AffectedSOPInstanceUID = "1.2.3.4"
    ds.ProcedureStepState = "SCHEDULED"
    ds.InputReadinessState = "READY"

    workitem = MagicMock(spec=WorkItem)
    workitem.uid = "1.2.3.4"
    workitem.ds = ds

    return workitem


@pytest.fixture
def sample_subscription() -> Subscription:
    """Create a sample subscription for testing."""
    return Subscription(workitem_uid="1.2.3.4", ae_title="TEST_AE", deletion_lock=False)


def test_initialization(notification_service: NotificationService, connection_manager: ConnectionManager) -> None:
    """Test that the notification service initializes correctly."""
    # Verify the connection_manager is properly stored
    assert notification_service.connection_manager == connection_manager

    # Verify the pending_notifications dictionary is initialized
    assert notification_service.pending_notifications == {}

    # Verify the callback is registered
    connection_manager.register_connection_callback.assert_called_once()


@patch("pyupsrs.domain.services.service_provider.ServiceProvider")
def test_queue_state_reports_specific_workitem(
    mock_service_provider: service_provider.ServiceProvider,
    notification_service: NotificationService,
    sample_workitem: WorkItem,
    sample_subscription: Subscription,
) -> None:
    """Test queueing state reports for a specific workitem subscription."""
    # Setup mock service provider to return the sample workitem
    mock_instance = mock_service_provider.get_instance.return_value
    mock_instance.workitem_repo.get_by_uid.return_value = sample_workitem

    # Call the method
    notification_service.queue_state_reports(sample_subscription)

    # Verify a state report was queued
    assert "TEST_AE" in notification_service.pending_notifications
    assert len(notification_service.pending_notifications["TEST_AE"]) == 1

    # Verify the workitem was retrieved correctly
    mock_instance.workitem_repo.get_by_uid.assert_called_once_with("1.2.3.4")

    # Verify the message content
    queued_message = notification_service.pending_notifications["TEST_AE"][0]
    assert queued_message.AffectedSOPInstanceUID == "1.2.3.4"
    assert queued_message.ProcedureStepState == "SCHEDULED"
    assert queued_message.InputReadinessState == "READY"


@patch("pyupsrs.domain.services.service_provider.ServiceProvider")
def test_queue_state_reports_global_subscription(
    mock_service_provider: service_provider.ServiceProvider, notification_service: NotificationService
) -> None:
    """Test queueing state reports for a global subscription with deletion lock."""
    # Create a global subscription
    global_subscription = Subscription(workitem_uid=GLOBAL_SUBSCRIPTION_UID, ae_title="GLOBAL_AE", deletion_lock=True)

    # Setup mock service provider to return multiple workitems
    mock_instance = mock_service_provider.get_instance.return_value
    workitem1 = MagicMock(spec=WorkItem)
    workitem1.uid = "1.2.3.4"
    workitem1.ds = Dataset()
    workitem1.ds.ProcedureStepState = "SCHEDULED"
    workitem1.ds.InputReadinessState = "READY"

    workitem2 = MagicMock(spec=WorkItem)
    workitem2.uid = "5.6.7.8"
    workitem2.ds = Dataset()
    workitem2.ds.ProcedureStepState = "IN PROGRESS"
    workitem2.ds.InputReadinessState = "READY"

    mock_instance.workitem_repo.get_all.return_value = [workitem1, workitem2]

    # Call the method
    notification_service.queue_state_reports(global_subscription)

    # Verify state reports were queued for both workitems
    assert "GLOBAL_AE" in notification_service.pending_notifications
    assert len(notification_service.pending_notifications["GLOBAL_AE"]) == 2

    # Verify the workitems were retrieved correctly
    mock_instance.workitem_repo.get_all.assert_called_once()

    # Verify the message content
    messages = notification_service.pending_notifications["GLOBAL_AE"]
    assert messages[0].AffectedSOPInstanceUID == "1.2.3.4"
    assert messages[0].ProcedureStepState == "SCHEDULED"
    assert messages[1].AffectedSOPInstanceUID == "5.6.7.8"
    assert messages[1].ProcedureStepState == "IN PROGRESS"


@patch("pyupsrs.domain.services.service_provider.ServiceProvider")
def test_queue_state_reports_filtered_subscription(
    mock_service_provider: service_provider.ServiceProvider, notification_service: NotificationService
) -> None:
    """Test queueing state reports for a filtered subscription."""
    # Create a filter
    filter_ds = Dataset()
    filter_ds.Modality = "CT"

    # Create a filtered subscription
    filtered_subscription = Subscription(
        workitem_uid=FILTERED_SUBSCRIPTION_UID, ae_title="FILTERED_AE", deletion_lock=False, filter=filter_ds
    )

    # Setup mock service provider and mock the match_query_to_dataset function
    mock_instance = mock_service_provider.get_instance.return_value
    workitem1 = MagicMock(spec=WorkItem)
    workitem1.uid = "1.2.3.4"
    workitem1.ds = Dataset()
    workitem1.ds.ProcedureStepState = "SCHEDULED"
    workitem1.ds.InputReadinessState = "READY"
    workitem1.ds.Modality = "CT"  # Should match

    workitem2 = MagicMock(spec=WorkItem)
    workitem2.uid = "5.6.7.8"
    workitem2.ds = Dataset()
    workitem2.ds.ProcedureStepState = "IN PROGRESS"
    workitem2.ds.InputReadinessState = "READY"
    workitem2.ds.Modality = "MR"  # Should not match

    mock_instance.workitem_repo.get_all.return_value = [workitem1, workitem2]

    # Mock the match_query_to_dataset function
    with patch("pyupsrs.websocket.notification_service.match_query_to_dataset") as mock_match:
        mock_match.side_effect = lambda filter, ds: ds.Modality == "CT"

        # Call the method
        notification_service.queue_state_reports(filtered_subscription)

        # Verify state report was queued only for the matching workitem
        assert "FILTERED_AE" in notification_service.pending_notifications
        assert len(notification_service.pending_notifications["FILTERED_AE"]) == 1

        # Verify the workitems were retrieved correctly
        mock_instance.workitem_repo.get_all.assert_called_once()

        # Verify the message content
        message = notification_service.pending_notifications["FILTERED_AE"][0]
        assert message.AffectedSOPInstanceUID == "1.2.3.4"
        assert message.ProcedureStepState == "SCHEDULED"


@pytest.mark.asyncio
async def test_on_connection_established(
    notification_service: NotificationService, connection_manager: ConnectionManager
) -> None:
    """Test processing pending notifications when a connection is established."""
    # Setup pending notifications
    ae_title = "TEST_AE"
    notification_service.pending_notifications[ae_title] = [
        create_ups_state_report("1.2.3.4", "SCHEDULED", "READY"),
        create_ups_state_report("5.6.7.8", "IN PROGRESS", "READY"),
    ]

    # Mock the send_message method to return True (success)
    connection_manager.send_message = AsyncMock(return_value=True)

    # Call the method
    await notification_service.on_connection_established(ae_title)

    # Verify that send_message was called for each notification
    assert connection_manager.send_message.call_count == 2

    # Verify that the pending notifications were cleared
    assert notification_service.pending_notifications[ae_title] == []


@pytest.mark.asyncio
async def test_on_connection_established_with_failures(
    notification_service: NotificationService, connection_manager: ConnectionManager
) -> None:
    """Test handling failures when sending pending notifications."""
    # Setup pending notifications
    ae_title = "TEST_AE"
    notification_service.pending_notifications[ae_title] = [
        create_ups_state_report("1.2.3.4", "SCHEDULED", "READY"),
        create_ups_state_report("5.6.7.8", "IN PROGRESS", "READY"),
    ]

    # Mock the send_message method to return False for the first call (failure) and True for the second
    connection_manager.send_message = AsyncMock(side_effect=[False, True])

    # Call the method
    await notification_service.on_connection_established(ae_title)

    # Verify that send_message was called for each notification
    assert connection_manager.send_message.call_count == 2

    # Verify that the pending notifications were cleared despite failures
    assert notification_service.pending_notifications[ae_title] == []


@pytest.mark.asyncio
async def test_on_connection_established_with_exceptions(
    notification_service: NotificationService, connection_manager: ConnectionManager
) -> None:
    """Test handling exceptions when sending pending notifications."""
    # Setup pending notifications
    ae_title = "TEST_AE"
    notification_service.pending_notifications[ae_title] = [
        create_ups_state_report("1.2.3.4", "SCHEDULED", "READY"),
        create_ups_state_report("5.6.7.8", "IN PROGRESS", "READY"),
    ]

    # Mock the send_message method to raise an exception for the first call and succeed for the second
    connection_manager.send_message = AsyncMock(side_effect=[Exception("Test exception"), True])

    # Call the method (should not raise an exception)
    await notification_service.on_connection_established(ae_title)

    # Verify that send_message was called for each notification
    assert connection_manager.send_message.call_count == 2

    # Verify that the pending notifications were cleared despite exceptions
    assert notification_service.pending_notifications[ae_title] == []
