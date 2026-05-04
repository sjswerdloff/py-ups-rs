"""Tests for SubscriptionRepository — CRUD operations and filter round-trip."""

import pytest
from pydicom import Dataset

from pyupsrs.domain.models.ups import GLOBAL_SUBSCRIPTION_UID, Subscription
from pyupsrs.storage.database import Database
from pyupsrs.storage.repositories.subscription_repository import SubscriptionRepository


@pytest.fixture
def repo() -> SubscriptionRepository:
    """Create a fresh in-memory repository for each test."""
    db = Database(":memory:")
    return SubscriptionRepository(database=db)


@pytest.fixture
def sample_subscription() -> Subscription:
    """Create a minimal subscription for testing."""
    return Subscription(
        workitem_uid=GLOBAL_SUBSCRIPTION_UID,
        ae_title="TEST_SCU",
        deletion_lock=False,
        contact_uri="http://example.com/notify",
    )


class TestCreate:
    """Contract: create persists a subscription."""

    def test_create_returns_subscription(self, repo: SubscriptionRepository, sample_subscription: Subscription) -> None:
        """Verify that create returns the subscription with the correct AE title."""
        result = repo.create(sample_subscription)
        assert result.ae_title == "TEST_SCU"

    def test_create_persists(self, repo: SubscriptionRepository, sample_subscription: Subscription) -> None:
        """Verify that the created subscription is retrievable by workitem and AE title."""
        repo.create(sample_subscription)
        result = repo.get_by_workitem_and_ae_title(sample_subscription.workitem_uid, sample_subscription.ae_title)
        assert len(result) == 1
        assert result[0].ae_title == "TEST_SCU"

    def test_create_replaces_suspended_equivalent(self, repo: SubscriptionRepository) -> None:
        """Verify that creating an active subscription replaces a suspended equivalent."""
        suspended = Subscription(
            workitem_uid=GLOBAL_SUBSCRIPTION_UID,
            ae_title="TEST_SCU",
            suspended=True,
        )
        repo.create(suspended)

        # Creating a non-suspended version should discard the suspended one
        active = Subscription(
            workitem_uid=GLOBAL_SUBSCRIPTION_UID,
            ae_title="TEST_SCU",
            suspended=False,
        )
        repo.create(active)

        result = repo.get_by_workitem_and_ae_title(GLOBAL_SUBSCRIPTION_UID, "TEST_SCU")
        assert len(result) == 1
        assert result[0].suspended is False


class TestGetByWorkitemAndAeTitle:
    """Contract: query by workitem + AE title returns matching subscriptions."""

    def test_found(self, repo: SubscriptionRepository, sample_subscription: Subscription) -> None:
        """Verify that a created subscription is found by workitem UID and AE title."""
        repo.create(sample_subscription)
        result = repo.get_by_workitem_and_ae_title(GLOBAL_SUBSCRIPTION_UID, "TEST_SCU")
        assert len(result) == 1

    def test_not_found(self, repo: SubscriptionRepository) -> None:
        """Verify that querying for an unknown combination returns an empty list."""
        result = repo.get_by_workitem_and_ae_title("1.2.3.4", "UNKNOWN")
        assert result == []


class TestGetByAeTitle:
    """Contract: query by AE title returns all subscriptions for that AE."""

    def test_multiple_subscriptions(self, repo: SubscriptionRepository) -> None:
        """Verify that all subscriptions for an AE title are returned."""
        sub1 = Subscription(workitem_uid="1.2.3.4", ae_title="MULTI_AE")
        sub2 = Subscription(workitem_uid="5.6.7.8", ae_title="MULTI_AE")
        repo.create(sub1)
        repo.create(sub2)
        result = repo.get_by_ae_title("MULTI_AE")
        assert len(result) == 2


class TestGetByWorkitem:
    """Contract: query by workitem UID returns all subscribers."""

    def test_multiple_subscribers(self, repo: SubscriptionRepository) -> None:
        """Verify that all subscribers for a workitem UID are returned."""
        sub1 = Subscription(workitem_uid=GLOBAL_SUBSCRIPTION_UID, ae_title="SCU_A")
        sub2 = Subscription(workitem_uid=GLOBAL_SUBSCRIPTION_UID, ae_title="SCU_B")
        repo.create(sub1)
        repo.create(sub2)
        result = repo.get_by_workitem(GLOBAL_SUBSCRIPTION_UID)
        assert len(result) == 2


class TestDelete:
    """Contract: delete removes the subscription and returns True/False."""

    def test_delete_existing(self, repo: SubscriptionRepository, sample_subscription: Subscription) -> None:
        """Verify that deleting an existing subscription returns True and removes it."""
        repo.create(sample_subscription)
        result = repo.delete(sample_subscription.workitem_uid, sample_subscription.ae_title)
        assert result is True
        remaining = repo.get_by_workitem_and_ae_title(sample_subscription.workitem_uid, sample_subscription.ae_title)
        assert remaining == []

    def test_delete_nonexistent(self, repo: SubscriptionRepository) -> None:
        """Verify that deleting a non-existent subscription returns False."""
        result = repo.delete("1.2.3.nonexistent", "UNKNOWN_AE")
        assert result is False


class TestFilterDatasetRoundTrip:
    """Contract: subscription filter Dataset is preserved through serialization."""

    def test_filter_none(self, repo: SubscriptionRepository) -> None:
        """Verify that a subscription with no filter round-trips with filter as None."""
        sub = Subscription(
            workitem_uid=GLOBAL_SUBSCRIPTION_UID,
            ae_title="NO_FILTER",
            filter=None,
        )
        repo.create(sub)
        result = repo.get_by_workitem_and_ae_title(GLOBAL_SUBSCRIPTION_UID, "NO_FILTER")
        assert result[0].filter is None

    def test_filter_dataset_preserved(self, repo: SubscriptionRepository) -> None:
        """Verify that filter Dataset attributes survive serialization and retrieval."""
        filter_ds = Dataset()
        filter_ds.PatientID = "FILTER-*"
        filter_ds.ProcedureStepState = "SCHEDULED"

        sub = Subscription(
            workitem_uid=GLOBAL_SUBSCRIPTION_UID,
            ae_title="FILTERED_SCU",
            filter=filter_ds,
        )
        repo.create(sub)

        result = repo.get_by_workitem_and_ae_title(GLOBAL_SUBSCRIPTION_UID, "FILTERED_SCU")
        assert result[0].filter is not None
        assert result[0].filter.PatientID == "FILTER-*"
        assert result[0].filter.ProcedureStepState == "SCHEDULED"
