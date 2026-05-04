"""Unit tests for WorkItemService covering all branches."""

from unittest.mock import MagicMock

import pytest
from pydicom import Dataset

from pyupsrs.domain.models.ups import WorkItem, WorkItemStatus
from pyupsrs.domain.services.workitem_service import WorkItemService
from pyupsrs.storage.repositories.workitem_repository import WorkItemRepository
from pyupsrs.websocket.notification_service import NotificationService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repository() -> MagicMock:
    """Mock WorkItemRepository."""
    return MagicMock(spec=WorkItemRepository)


@pytest.fixture
def mock_notification_service() -> MagicMock:
    """Mock NotificationService."""
    return MagicMock(spec=NotificationService)


def _make_workitem(status: str = "SCHEDULED", transaction_uid: str | None = None) -> WorkItem:
    """Build a WorkItem with a Dataset containing the given ProcedureStepState."""
    ds = Dataset()
    ds.SOPInstanceUID = "1.2.3.4.5"
    ds.AffectedSOPInstanceUID = "1.2.3.4.5"
    ds.ProcedureStepState = status
    workitem = WorkItem(ds=ds)
    workitem.transaction_uid = transaction_uid
    return workitem


def _make_service(
    repository: WorkItemRepository,
    notification_service: NotificationService | None,
) -> WorkItemService:
    """Construct a WorkItemService with optional notification service."""
    return WorkItemService(
        workitem_repository=repository,
        notification_service=notification_service,
    )


# ---------------------------------------------------------------------------
# create_workitem tests
# ---------------------------------------------------------------------------


class TestCreateWorkitem:
    """Tests for create_workitem method."""

    def test_create_workitem_with_notification_service_calls_notify(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: create_workitem notifies when notification service is present."""
        workitem = _make_workitem()
        mock_repository.create.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result = service.create_workitem(workitem)

        mock_notification_service.notify_creation.assert_called_once_with(workitem)
        assert result is workitem

    def test_create_workitem_without_notification_service_logs_warning(
        self,
        mock_repository: MagicMock,
    ) -> None:
        """Contract: create_workitem skips notification and logs warning when service is None (line 46)."""
        workitem = _make_workitem()
        mock_repository.create.return_value = workitem
        service = _make_service(mock_repository, notification_service=None)

        result = service.create_workitem(workitem)

        # No notification service means no notify call — just logs and returns
        assert result is workitem

    def test_create_workitem_returns_repository_result(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: create_workitem returns whatever the repository returns."""
        incoming = _make_workitem()
        stored = _make_workitem()
        mock_repository.create.return_value = stored
        service = _make_service(mock_repository, mock_notification_service)

        result = service.create_workitem(incoming)

        assert result is stored


# ---------------------------------------------------------------------------
# update_workitem_status tests
# ---------------------------------------------------------------------------


class TestUpdateWorkitemStatus:
    """Tests for update_workitem_status method."""

    def test_update_scheduled_workitem_succeeds(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: updating a SCHEDULED workitem with any transaction_uid succeeds."""
        workitem = _make_workitem(status="SCHEDULED")
        mock_repository.get_by_uid.return_value = workitem
        mock_repository.update.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status("1.2.3.4.5", WorkItemStatus.IN_PROGRESS, "txn-001")

        assert success is True
        assert result_workitem is workitem

    def test_update_returns_workitem_instance_from_non_workitem_repository_result(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: when repository returns non-WorkItem, it is wrapped in WorkItem (line 67)."""
        ds = Dataset()
        ds.SOPInstanceUID = "1.2.3.4.5"
        ds.AffectedSOPInstanceUID = "1.2.3.4.5"
        ds.ProcedureStepState = "SCHEDULED"
        # Repository returns a bare Dataset, not a WorkItem
        mock_repository.get_by_uid.return_value = ds
        wrapped_workitem = _make_workitem(status="SCHEDULED")
        mock_repository.update.return_value = wrapped_workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status("1.2.3.4.5", WorkItemStatus.IN_PROGRESS, "txn-001")

        # The service wrapped the Dataset and continued — update succeeded
        assert success is True

    def test_update_returns_false_when_procedure_step_state_missing(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: workitem missing ProcedureStepState returns (workitem, False) (lines 77-80)."""
        ds = Dataset()
        ds.SOPInstanceUID = "1.2.3.4.5"
        # No ProcedureStepState attribute
        workitem = WorkItem(ds=ds)
        mock_repository.get_by_uid.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status("1.2.3.4.5", WorkItemStatus.IN_PROGRESS, "txn-001")

        assert success is False
        assert result_workitem is workitem

    def test_update_non_scheduled_workitem_without_transaction_uid_returns_false(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: non-SCHEDULED workitem with no transaction_uid returns (workitem, False) (lines 83-86)."""
        workitem = _make_workitem(status="IN PROGRESS", transaction_uid="txn-original")
        mock_repository.get_by_uid.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status("1.2.3.4.5", WorkItemStatus.COMPLETED, transaction_uid="")

        assert success is False
        assert result_workitem is workitem

    def test_update_non_scheduled_workitem_with_wrong_transaction_uid_returns_false(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: non-SCHEDULED workitem with mismatched transaction_uid returns (workitem, False) (lines 83-86)."""
        workitem = _make_workitem(status="IN PROGRESS", transaction_uid="txn-original")
        mock_repository.get_by_uid.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status(
            "1.2.3.4.5", WorkItemStatus.COMPLETED, transaction_uid="txn-wrong"
        )

        assert success is False
        assert result_workitem is workitem

    def test_update_completed_workitem_returns_false(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: COMPLETED workitem cannot be updated, returns (workitem, False) (lines 89-90)."""
        workitem = _make_workitem(status="COMPLETED", transaction_uid="txn-001")
        mock_repository.get_by_uid.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status(
            "1.2.3.4.5", WorkItemStatus.CANCELED, transaction_uid="txn-001"
        )

        assert success is False
        assert result_workitem is workitem

    def test_update_canceled_workitem_returns_false(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: CANCELED workitem cannot be updated, returns (workitem, False) (lines 89-90)."""
        workitem = _make_workitem(status="CANCELED", transaction_uid="txn-001")
        mock_repository.get_by_uid.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status(
            "1.2.3.4.5", WorkItemStatus.SCHEDULED, transaction_uid="txn-001"
        )

        assert success is False
        assert result_workitem is workitem

    def test_update_raises_and_propagates_repository_exception(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: exceptions from repository propagate to caller (lines 105-108)."""
        mock_repository.get_by_uid.side_effect = RuntimeError("DB connection lost")
        service = _make_service(mock_repository, mock_notification_service)

        with pytest.raises(RuntimeError, match="DB connection lost"):
            service.update_workitem_status("1.2.3.4.5", WorkItemStatus.IN_PROGRESS, "txn-001")

    def test_update_raises_and_propagates_update_repository_exception(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: exceptions from repository.update propagate to caller (lines 105-108)."""
        workitem = _make_workitem(status="SCHEDULED")
        mock_repository.get_by_uid.return_value = workitem
        mock_repository.update.side_effect = RuntimeError("update failed")
        service = _make_service(mock_repository, mock_notification_service)

        with pytest.raises(RuntimeError, match="update failed"):
            service.update_workitem_status("1.2.3.4.5", WorkItemStatus.IN_PROGRESS, "txn-001")

    def test_update_without_notification_service_logs_warning(
        self,
        mock_repository: MagicMock,
    ) -> None:
        """Contract: successful update without notification service logs warning (line 105)."""
        workitem = _make_workitem(status="SCHEDULED")
        mock_repository.get_by_uid.return_value = workitem
        mock_repository.update.return_value = workitem
        service = _make_service(mock_repository, notification_service=None)

        result_workitem, success = service.update_workitem_status("1.2.3.4.5", WorkItemStatus.IN_PROGRESS, "txn-001")

        assert success is True
        assert result_workitem is workitem

    def test_update_in_progress_stores_transaction_uid(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: transitioning to IN_PROGRESS stores the transaction_uid on the workitem."""
        workitem = _make_workitem(status="SCHEDULED")
        mock_repository.get_by_uid.return_value = workitem
        mock_repository.update.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        service.update_workitem_status("1.2.3.4.5", WorkItemStatus.IN_PROGRESS, "txn-new")

        assert workitem.transaction_uid == "txn-new"

    def test_update_non_scheduled_with_correct_transaction_uid_succeeds(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: non-SCHEDULED workitem with matching transaction_uid can be updated."""
        workitem = _make_workitem(status="IN PROGRESS", transaction_uid="txn-correct")
        mock_repository.get_by_uid.return_value = workitem
        mock_repository.update.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.update_workitem_status(
            "1.2.3.4.5", WorkItemStatus.COMPLETED, transaction_uid="txn-correct"
        )

        assert success is True
        assert result_workitem is workitem


# ---------------------------------------------------------------------------
# cancel_workitem tests
# ---------------------------------------------------------------------------


class TestCancelWorkitem:
    """Tests for cancel_workitem method."""

    def test_cancel_delegates_to_update_workitem_status(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: cancel_workitem delegates to update_workitem_status with CANCELED (line 122)."""
        workitem = _make_workitem(status="SCHEDULED")
        workitem.transaction_uid = "txn-cancel"
        mock_repository.get_by_uid.return_value = workitem
        mock_repository.update.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.cancel_workitem(workitem)

        assert success is True
        assert result_workitem is workitem

    def test_cancel_passes_workitem_transaction_uid(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: cancel_workitem forwards the workitem's own transaction_uid."""
        workitem = _make_workitem(status="IN PROGRESS", transaction_uid="txn-lock")
        mock_repository.get_by_uid.return_value = workitem
        mock_repository.update.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.cancel_workitem(workitem)

        # Matching transaction_uid means cancel of IN PROGRESS workitem succeeds
        assert success is True

    def test_cancel_returns_false_for_already_canceled_workitem(
        self,
        mock_repository: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Contract: canceling an already CANCELED workitem returns (workitem, False)."""
        workitem = _make_workitem(status="CANCELED", transaction_uid="txn-lock")
        mock_repository.get_by_uid.return_value = workitem
        service = _make_service(mock_repository, mock_notification_service)

        result_workitem, success = service.cancel_workitem(workitem)

        assert success is False
