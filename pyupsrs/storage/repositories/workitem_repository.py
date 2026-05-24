"""Repository for accessing UPS workitems via SQLite persistence."""

from copy import deepcopy
from datetime import datetime
from typing import Any

from pydicom import Dataset
from pydicom.datadict import keyword_for_tag

from pyupsrs.domain.models.ups import WorkItem, WorkItemStatus
from pyupsrs.storage.database import Database
from pyupsrs.utils.class_logger import LoggerMixin
from pyupsrs.utils.dicom_query_matcher import query_datasets


class WorkItemRepository(LoggerMixin):
    """Repository for UPS workitems backed by SQLite."""

    _COLUMNS: tuple[str, ...] = (
        "uid",
        "status",
        "dataset_json",
        "created_at",
        "updated_at",
        "transaction_uid",
        "scheduled_start_time",
        "scheduled_end_time",
        "patient_name",
        "patient_id",
        "accession_number",
        "procedure_step_type",
        "procedure_code",
    )

    def __init__(self, database: Database) -> None:
        """
        Initialize the repository.

        Args:
            database: The Database instance for persistence.

        """
        self._db = database

    @classmethod
    def _build_params(cls, row: dict[str, Any]) -> tuple[Any, ...]:
        """
        Extract column values from a row dict in canonical column order.

        Args:
            row: Dictionary mapping column names to values.

        Returns:
            Tuple of values in the order defined by ``_COLUMNS``.

        """
        return tuple(row[col] for col in cls._COLUMNS)

    def create(self, workitem: WorkItem) -> WorkItem:
        """
        Create a new workitem.

        Args:
            workitem: The workitem to create.

        Returns:
            The created workitem.

        """
        row = self._workitem_to_row(workitem)
        columns_sql = ", ".join(self._COLUMNS)
        placeholders = ", ".join("?" * len(self._COLUMNS))
        self._db.execute(
            f"INSERT INTO workitems ({columns_sql}) VALUES ({placeholders})",
            self._build_params(row),
        )
        return workitem

    def get_by_uid(self, uid: str) -> WorkItem | None:
        """
        Get a workitem by UID.

        Args:
            uid: The UID of the workitem.

        Returns:
            The workitem, or None if not found.

        """
        row = self._db.fetch_one("SELECT * FROM workitems WHERE uid = ?", (uid,))
        if row is None:
            return None
        return self._row_to_workitem(row)

    def update(self, workitem: WorkItem) -> WorkItem:
        """
        Update a workitem by merging the change dataset into the stored one.

        Args:
            workitem: The workitem containing changes to apply.

        Returns:
            The updated workitem.

        """
        if not workitem.uid:
            self.logger.error("No UID in change/update workitem")
            return workitem

        stored = self.get_by_uid(workitem.uid)
        if stored is None:
            self.logger.error(f"Unable to find stored workitem with uid: {workitem.uid}")
            return workitem

        if workitem.ds:
            if stored.ds:
                stored.ds.update(workitem.ds)
            else:
                self.logger.error(f"Unable to find dataset in stored workitem {workitem.uid}")
                return stored
        else:
            self.logger.warning("No Change Dataset in update")

        # Sync non-dataset fields that the service layer may have updated directly
        if workitem.transaction_uid is not None:
            stored.transaction_uid = workitem.transaction_uid
        if workitem.status != stored.status:
            stored.status = workitem.status

        stored.updated_at = datetime.now()
        row = self._workitem_to_row(stored)
        set_columns = [col for col in self._COLUMNS if col != "uid"]
        set_clause = ", ".join(f"{col} = ?" for col in set_columns)
        set_params = tuple(row[col] for col in set_columns)
        self._db.execute(
            f"UPDATE workitems SET {set_clause} WHERE uid = ?",
            (*set_params, row["uid"]),
        )
        return stored

    def delete(self, uid: str) -> bool:
        """
        Delete a workitem.

        Args:
            uid: The UID of the workitem.

        Returns:
            True if deleted, False otherwise.

        """
        self._db.execute("DELETE FROM workitems WHERE uid = ?", (uid,))
        return True

    def cancel(self, uid: str, cancel_workitem: WorkItem) -> bool:
        """
        Cancel a workitem.

        Args:
            uid: The UID of the workitem.
            cancel_workitem: The workitem containing cancellation data.

        Returns:
            True if canceled, False otherwise.

        """
        stored = self.get_by_uid(uid)
        if stored is None:
            self.logger.error(f"Unable to find workitem to cancel: {uid}")
            return False

        stored.status = cancel_workitem.status
        if cancel_workitem.ds:
            stored.ds.update(cancel_workitem.ds)

        self.update(stored)
        return True

    def get_all(self) -> list[WorkItem]:
        """
        Get all workitems.

        Returns:
            A list of all workitems.

        """
        rows = self._db.fetch_all("SELECT * FROM workitems")
        return [self._row_to_workitem(row) for row in rows]

    def get_filtered(
        self,
        match: Dataset = None,
        include_field: list[str] = None,
        fuzzy_matching: Any = None,  # noqa: ANN401
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[WorkItem]:
        """
        Filter list of workitems.

        Args:
            match: Exact matching query elements.
            include_field: List of tags to include in response.
            fuzzy_matching: Whether to use fuzzy matching for persons name.
            offset: Starting point of list to return.
            limit: Maximum size of returned list.

        Returns:
            Filtered list of workitems.

        """
        self.logger.warning("Fuzzy Matching not implemented")
        if not match and not include_field and not fuzzy_matching:
            return self.get_all()

        # Load all workitems and filter using DICOM query matching
        all_workitems = self.get_all()
        datasets = [x.ds for x in all_workitems]
        matching_datasets = query_datasets(query=match, datasets=datasets)
        uid_list: list[str] = []
        for matching_ds in matching_datasets:
            # SOPInstanceUID (0008,0018) is preferred; AffectedSOPInstanceUID
            # (0000,1000) is the legacy fallback. Skip datasets that have
            # neither (orphaned rows from earlier development cycles); they
            # cannot be looked up by UID and would otherwise raise
            # AttributeError on str(ds.SOPInstanceUID), surfacing as a 500.
            ds_uid = getattr(matching_ds, "SOPInstanceUID", None) or getattr(matching_ds, "AffectedSOPInstanceUID", None)
            if ds_uid is None:
                self.logger.warning("Skipping matched workitem dataset without SOPInstanceUID or AffectedSOPInstanceUID")
                continue
            uid_list.append(str(ds_uid))
        matching_workitems = [wi for wi in all_workitems if wi.uid in uid_list]
        copy_of_workitems = deepcopy(matching_workitems)

        if include_field and "all" not in include_field:
            include_keywords = [keyword_for_tag(int(kw, 16)) if kw.isnumeric() else kw for kw in include_field]
            self.logger.warning(f"Includefield as keywords {include_keywords}")
            self.logger.warning(f"includefield was specified and will restrict content returned: {include_field}")
            for workitem in copy_of_workitems:
                for elem in workitem.ds:
                    if elem.keyword not in include_keywords:
                        del workitem.ds[elem.keyword]

        return copy_of_workitems[offset:limit]

    @staticmethod
    def _workitem_to_row(workitem: WorkItem) -> dict[str, Any]:
        """
        Convert a WorkItem to a dictionary suitable for database storage.

        Args:
            workitem: The workitem to serialize.

        Returns:
            Dictionary with column names as keys.

        """
        ds = workitem.ds or Dataset()
        return {
            "uid": workitem.uid,
            "status": workitem.status.value if isinstance(workitem.status, WorkItemStatus) else str(workitem.status),
            "dataset_json": ds.to_json() if workitem.ds else "{}",
            "created_at": workitem.created_at.isoformat() if workitem.created_at else datetime.now().isoformat(),
            "updated_at": workitem.updated_at.isoformat() if workitem.updated_at else None,
            "transaction_uid": workitem.transaction_uid,
            "scheduled_start_time": str(ds.get("ScheduledProcedureStepStartDateTime", "")) or None,
            "scheduled_end_time": str(ds.get("ScheduledProcedureStepEndDateTime", "")) or None,
            "patient_name": str(ds.get("PatientName", "")) or None,
            "patient_id": str(ds.get("PatientID", "")) or None,
            "accession_number": str(ds.get("AccessionNumber", "")) or None,
            "procedure_step_type": str(ds.get("ScheduledWorkitemCodeSequence", "")) or None,
            "procedure_code": str(ds.get("ProcedureCodeSequence", "")) or None,
        }

    @staticmethod
    def _row_to_workitem(row: dict[str, Any]) -> WorkItem:
        """
        Reconstruct a WorkItem from a database row.

        Args:
            row: The database row as a dictionary.

        Returns:
            A WorkItem instance.

        """
        from pydicom.dataset import Dataset as PydicomDataset

        dataset_json = row.get("dataset_json", "{}")
        ds = PydicomDataset.from_json(dataset_json) if dataset_json else PydicomDataset()

        workitem = WorkItem(ds=ds)
        workitem.status = WorkItemStatus.from_string(row["status"])
        workitem.created_at = datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now()
        workitem.updated_at = datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else None
        workitem.transaction_uid = row.get("transaction_uid")
        return workitem
