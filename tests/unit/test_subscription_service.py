"""Tests for the subscription service with notification queueing."""

from unittest.mock import MagicMock, patch

import pytest

from pyupsrs.domain.models.ups import GLOBAL_SUBSCRIPTION_UID, Subscription
from pyupsrs.domain.services.service_provider import ServiceProvider
from pyupsrs.domain.services.subscription_service import SubscriptionService
from pyupsrs.storage.repositories.subscription_repository import SubscriptionRepository


@pytest.fixture
def subscription_repository() -> SubscriptionRepository:
    """Create a subscription repository for testing."""
    repo = MagicMock(spec=SubscriptionRepository)
    # Configure the repo to return the input subscription from create()
    repo.create.side_effect = lambda sub: sub
    return repo


@pytest.fixture
def subscription_service(subscription_repository: SubscriptionRepository) -> SubscriptionService:
    """Create a subscription service for testing."""
    return SubscriptionService(subscription_repository)


@pytest.fixture
def sample_subscription() -> Subscription:
    """Create a sample subscription for testing."""
    return Subscription(workitem_uid="1.2.3.4", ae_title="TEST_AE", deletion_lock=False)


@pytest.fixture
def global_subscription() -> Subscription:
    """Create a global subscription for testing."""
    return Subscription(workitem_uid=GLOBAL_SUBSCRIPTION_UID, ae_title="GLOBAL_AE", deletion_lock=True)


@patch("pyupsrs.domain.services.service_provider.ServiceProvider")
def test_create_subscription(
    mock_service_provider: ServiceProvider,
    subscription_service: SubscriptionService,
    subscription_repository: SubscriptionRepository,
    sample_subscription: Subscription,
) -> None:
    """Test creating a subscription with notification queueing."""
    # Setup mocks
    mock_instance = mock_service_provider.get_instance.return_value
    mock_connection_manager = MagicMock()
    mock_notification_service = MagicMock()

    mock_instance.connection_manager = mock_connection_manager
    mock_instance.notification_service = mock_notification_service

    # Call the method
    subscription_service.create_subscription(sample_subscription)

    # Verify the subscription was stored in the connection manager
    mock_connection_manager.subscribe.assert_called_once_with(sample_subscription.ae_title, sample_subscription.workitem_uid)

    # Verify the subscription was persisted in the repository
    subscription_repository.create.assert_called_once_with(sample_subscription)

    # Verify initial state reports were queued
    mock_notification_service.queue_state_reports.assert_called_once_with(sample_subscription)


@patch("pyupsrs.domain.services.service_provider.ServiceProvider")
def test_create_subscription_global(
    mock_service_provider: ServiceProvider,
    subscription_service: SubscriptionService,
    subscription_repository: SubscriptionRepository,
    global_subscription: Subscription,
) -> None:
    """Test creating a global subscription with notification queueing."""
    # Setup mocks
    mock_instance = mock_service_provider.get_instance.return_value
    mock_connection_manager = MagicMock()
    mock_notification_service = MagicMock()

    mock_instance.connection_manager = mock_connection_manager
    mock_instance.notification_service = mock_notification_service

    # Call the method
    subscription_service.create_subscription(global_subscription)

    # Verify the subscription was stored in the connection manager
    mock_connection_manager.subscribe.assert_called_once_with(global_subscription.ae_title, global_subscription.workitem_uid)

    # Verify the subscription was persisted in the repository
    subscription_repository.create.assert_called_once_with(global_subscription)

    # Verify initial state reports were queued
    mock_notification_service.queue_state_reports.assert_called_once_with(global_subscription)


@patch("pyupsrs.domain.services.service_provider.ServiceProvider")
def test_create_subscription_error_handling(
    mock_service_provider: ServiceProvider,
    subscription_service: SubscriptionService,
    subscription_repository: SubscriptionRepository,
    sample_subscription: Subscription,
) -> None:
    """Test error handling during notification queueing."""
    # Setup mocks
    mock_instance = mock_service_provider.get_instance.return_value
    mock_connection_manager = MagicMock()
    mock_notification_service = MagicMock()

    # Configure the notification service to raise an exception
    mock_notification_service.queue_state_reports.side_effect = Exception("Test exception")

    mock_instance.connection_manager = mock_connection_manager
    mock_instance.notification_service = mock_notification_service

    # Call the method (should not raise an exception)
    result = subscription_service.create_subscription(sample_subscription)

    # Verify the subscription was still stored in the connection manager
    mock_connection_manager.subscribe.assert_called_once_with(sample_subscription.ae_title, sample_subscription.workitem_uid)

    # Verify the subscription was still persisted in the repository
    subscription_repository.create.assert_called_once_with(sample_subscription)

    # Verify notification queueing was attempted
    mock_notification_service.queue_state_reports.assert_called_once_with(sample_subscription)

    # Verify the method still returned the created subscription
    assert result == sample_subscription


@patch("pyupsrs.domain.services.service_provider.ServiceProvider")
def test_delete_subscription(
    mock_service_provider: ServiceProvider,
    subscription_service: SubscriptionService,
    subscription_repository: SubscriptionRepository,
) -> None:
    """Test deleting a subscription."""
    # Setup mocks
    mock_instance = mock_service_provider.get_instance.return_value
    mock_connection_manager = MagicMock()
    mock_instance.connection_manager = mock_connection_manager

    # Configure the repository to return True for successful deletion
    subscription_repository.delete.return_value = True

    # Call the method
    workitem_uid = "1.2.3.4"
    ae_title = "TEST_AE"
    result = subscription_service.delete_subscription(workitem_uid, ae_title)

    # Verify the subscription was removed from the connection manager
    mock_connection_manager.unsubscribe.assert_called_once_with(ae_title, workitem_uid)

    # Verify the subscription was deleted from the repository
    subscription_repository.delete.assert_called_once_with(workitem_uid, ae_title)

    # Verify the result
    assert result is True
