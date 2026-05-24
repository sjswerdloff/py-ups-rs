"""Tests for WorkItemRepository — CRUD operations and Dataset round-trip fidelity."""

import pytest
from pydicom import Dataset
from pydicom.uid import generate_uid

from pyupsrs.domain.models.ups import WorkItem, WorkItemStatus
from pyupsrs.storage.database import Database
from pyupsrs.storage.repositories.workitem_repository import WorkItemRepository


@pytest.fixture
def repo() -> WorkItemRepository:
    """Create a fresh in-memory repository for each test."""
    db = Database(":memory:")
    return WorkItemRepository(database=db)


@pytest.fixture
def sample_workitem() -> WorkItem:
    """Create a minimal valid WorkItem with a Dataset."""
    ds = Dataset()
    ds.SOPInstanceUID = generate_uid()
    ds.PatientName = "Test^Patient"
    ds.PatientID = "PAT-001"
    ds.ProcedureStepState = "SCHEDULED"
    workitem = WorkItem(ds=ds)
    workitem.status = WorkItemStatus.SCHEDULED
    return workitem


class TestCreate:
    """Contract: create persists a workitem and it can be retrieved."""

    def test_create_returns_workitem(self, repo: WorkItemRepository, sample_workitem: WorkItem) -> None:
        """Verify that create returns the workitem with the same UID."""
        result = repo.create(sample_workitem)
        assert result.uid == sample_workitem.uid

    def test_create_persists_to_db(self, repo: WorkItemRepository, sample_workitem: WorkItem) -> None:
        """Verify that the created workitem is retrievable by UID."""
        repo.create(sample_workitem)
        retrieved = repo.get_by_uid(sample_workitem.uid)
        assert retrieved is not None
        assert retrieved.uid == sample_workitem.uid

    def test_create_persists_dataset_json(self, repo: WorkItemRepository, sample_workitem: WorkItem) -> None:
        """Verify that DICOM dataset attributes survive a create and retrieve cycle."""
        repo.create(sample_workitem)
        retrieved = repo.get_by_uid(sample_workitem.uid)
        assert str(retrieved.ds.PatientName) == "Test^Patient"
        assert retrieved.ds.PatientID == "PAT-001"


class TestGetByUid:
    """Contract: get_by_uid returns the workitem or None."""

    def test_existing_uid(self, repo: WorkItemRepository, sample_workitem: WorkItem) -> None:
        """Verify that get_by_uid finds a previously created workitem."""
        repo.create(sample_workitem)
        result = repo.get_by_uid(sample_workitem.uid)
        assert result is not None

    def test_nonexistent_uid(self, repo: WorkItemRepository) -> None:
        """Verify that get_by_uid returns None for an unknown UID."""
        result = repo.get_by_uid("1.2.3.4.5.nonexistent")
        assert result is None


class TestUpdate:
    """Contract: update merges change dataset into stored workitem."""

    def test_update_modifies_stored_data(self, repo: WorkItemRepository, sample_workitem: WorkItem) -> None:
        """Verify that update writes changed attributes and preserves unchanged ones."""
        repo.create(sample_workitem)

        change_ds = Dataset()
        change_ds.SOPInstanceUID = sample_workitem.uid
        change_ds.PatientName = "Updated^Name"
        change_workitem = WorkItem(ds=change_ds)

        result = repo.update(change_workitem)
        assert str(result.ds.PatientName) == "Updated^Name"

        # Verify persisted
        stored = repo.get_by_uid(sample_workitem.uid)
        assert str(stored.ds.PatientName) == "Updated^Name"
        # Original fields preserved
        assert stored.ds.PatientID == "PAT-001"

    def test_update_nonexistent_returns_input(self, repo: WorkItemRepository) -> None:
        """Verify that updating a non-existent UID returns the input workitem unchanged."""
        ds = Dataset()
        ds.SOPInstanceUID = "1.2.3.4.nonexistent"
        workitem = WorkItem(ds=ds)
        result = repo.update(workitem)
        assert result.uid == "1.2.3.4.nonexistent"


class TestDelete:
    """Contract: delete removes the workitem."""

    def test_delete_existing(self, repo: WorkItemRepository, sample_workitem: WorkItem) -> None:
        """Verify that deleting an existing workitem returns True and removes it."""
        repo.create(sample_workitem)
        result = repo.delete(sample_workitem.uid)
        assert result is True
        assert repo.get_by_uid(sample_workitem.uid) is None

    def test_delete_nonexistent(self, repo: WorkItemRepository) -> None:
        """Verify that deleting a non-existent workitem returns True without error."""
        # DELETE WHERE uid = ? on missing row is not an error
        result = repo.delete("1.2.3.nonexistent")
        assert result is True


class TestCancel:
    """Contract: cancel updates status and merges cancellation data."""

    def test_cancel_updates_status(self, repo: WorkItemRepository, sample_workitem: WorkItem) -> None:
        """Verify that cancel sets the workitem status to CANCELED."""
        repo.create(sample_workitem)

        cancel_ds = Dataset()
        cancel_ds.SOPInstanceUID = sample_workitem.uid
        cancel_ds.ProcedureStepState = "CANCELED"
        cancel_workitem = WorkItem(ds=cancel_ds)
        cancel_workitem.status = WorkItemStatus.CANCELED

        result = repo.cancel(sample_workitem.uid, cancel_workitem)
        assert result is True

        stored = repo.get_by_uid(sample_workitem.uid)
        assert stored.status == WorkItemStatus.CANCELED

    def test_cancel_nonexistent_returns_false(self, repo: WorkItemRepository) -> None:
        """Verify that canceling a non-existent workitem returns False."""
        ds = Dataset()
        ds.SOPInstanceUID = "1.2.3.nonexistent"
        cancel_workitem = WorkItem(ds=ds)
        cancel_workitem.status = WorkItemStatus.CANCELED
        result = repo.cancel("1.2.3.nonexistent", cancel_workitem)
        assert result is False


class TestGetAll:
    """Contract: get_all returns all stored workitems."""

    def test_empty_repo(self, repo: WorkItemRepository) -> None:
        """Verify that get_all returns an empty list when no workitems exist."""
        result = repo.get_all()
        assert result == []

    def test_multiple_workitems(self, repo: WorkItemRepository) -> None:
        """Verify that get_all returns all inserted workitems."""
        for i in range(3):
            ds = Dataset()
            ds.SOPInstanceUID = generate_uid()
            ds.PatientID = f"PAT-{i:03d}"
            repo.create(WorkItem(ds=ds))

        result = repo.get_all()
        assert len(result) == 3


class TestGetFilteredOrphanedWorkitems:
    """
    Contract: get_filtered must not crash on rows lacking SOPInstanceUID.

    Orphaned workitem rows (from earlier development cycles where
    SOPInstanceUID was not injected from the URL on create) have
    neither (0008,0018) SOPInstanceUID nor (0000,1000)
    AffectedSOPInstanceUID. Previously get_filtered raised
    AttributeError on ``str(ds.SOPInstanceUID)``, surfacing as a
    500 to the API caller. The fix silently skips such rows.
    """

    def _insert_orphan_row(self, repo: WorkItemRepository) -> None:
        """Insert a workitem row with no SOPInstanceUID via direct SQL."""
        # Mimic the legacy bad state: dataset_json has filterable content
        # (status, patient ID) but no SOPInstanceUID / AffectedSOPInstanceUID.
        orphan_json = (
            '{"00100010": {"vr": "PN", '
            '"Value": [{"Alphabetic": "Orphan^Patient"}]}, '
            '"00100020": {"vr": "LO", "Value": ["ORPHAN-001"]}, '
            '"00741000": {"vr": "CS", "Value": ["SCHEDULED"]}}'
        )
        repo._db.execute(
            "INSERT INTO workitems (uid, status, dataset_json, created_at) VALUES (?, ?, ?, ?)",
            ("orphan-no-sop-uid", "SCHEDULED", orphan_json, "1970-01-01"),
        )

    def test_filter_with_orphaned_row_does_not_crash(self, repo: WorkItemRepository) -> None:
        """Verify filtered search skips orphans rather than raising."""
        # A normal workitem the filter should match.
        good_uid = generate_uid()
        ds = Dataset()
        ds.SOPInstanceUID = good_uid
        ds.PatientName = "Real^Patient"
        ds.ProcedureStepState = "SCHEDULED"
        wi = WorkItem(ds=ds)
        wi.status = WorkItemStatus.SCHEDULED
        repo.create(wi)

        # An orphan row that would otherwise raise AttributeError.
        self._insert_orphan_row(repo)

        query = Dataset()
        query.ProcedureStepState = "SCHEDULED"

        results = repo.get_filtered(match=query)

        # The good workitem is returned; the orphan is silently dropped.
        returned_uids = [r.uid for r in results]
        assert good_uid in returned_uids
        # Orphan uid (as stored in the uid column) is NOT in returned set
        # because get_filtered re-keys by the dataset's SOPInstanceUID,
        # which the orphan does not have.
        assert "orphan-no-sop-uid" not in returned_uids


class TestDatasetRoundTrip:
    """Contract: Dataset serialization preserves all DICOM attributes."""

    def test_person_name_preserved(self, repo: WorkItemRepository) -> None:
        """Verify that a multi-component person name survives serialization."""
        ds = Dataset()
        ds.SOPInstanceUID = generate_uid()
        ds.PatientName = "Family^Given^Middle^Prefix^Suffix"
        repo.create(WorkItem(ds=ds))

        stored = repo.get_by_uid(str(ds.SOPInstanceUID))
        assert str(stored.ds.PatientName) == "Family^Given^Middle^Prefix^Suffix"

    def test_sequence_preserved(self, repo: WorkItemRepository) -> None:
        """Verify that DICOM sequence items survive serialization."""
        ds = Dataset()
        ds.SOPInstanceUID = generate_uid()
        item = Dataset()
        item.CodeValue = "T-D1100"
        item.CodingSchemeDesignator = "SRT"
        item.CodeMeaning = "Breast"
        ds.AnatomicRegionSequence = [item]
        repo.create(WorkItem(ds=ds))

        stored = repo.get_by_uid(str(ds.SOPInstanceUID))
        assert stored.ds.AnatomicRegionSequence[0].CodeValue == "T-D1100"

    def test_status_round_trip(self, repo: WorkItemRepository) -> None:
        """Verify that workitem status is preserved through storage and retrieval."""
        ds = Dataset()
        ds.SOPInstanceUID = generate_uid()
        ds.ProcedureStepState = "SCHEDULED"
        workitem = WorkItem(ds=ds)
        workitem.status = WorkItemStatus.SCHEDULED
        repo.create(workitem)

        stored = repo.get_by_uid(str(ds.SOPInstanceUID))
        assert stored.status == WorkItemStatus.SCHEDULED
