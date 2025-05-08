"""Repository for accessing UPS workitems."""

from copy import deepcopy
from datetime import datetime
from typing import Any

from pydicom import Dataset
from pydicom.datadict import keyword_for_tag

from pyupsrs.domain.models.ups import WorkItem
from pyupsrs.utils.class_logger import LoggerMixin
from pyupsrs.utils.dicom_query_matcher import query_datasets

local_store: dict[str, WorkItem] = {}


class WorkItemRepository(LoggerMixin):
    """Repository for UPS workitems."""

    def __init__(self, database_uri: str) -> None:
        """
        Initialize the repository.

        Args:
            database_uri: The URI for the database.

        """
        self.database_uri = database_uri

    def create(self, workitem: WorkItem) -> WorkItem:
        """
        Create a new workitem.

        Args:
            workitem: The workitem to create.

        Returns:
            The created workitem.

        """
        # TODO: Implement database persistence
        local_store[workitem.uid] = workitem
        return workitem

    def get_by_uid(self, uid: str) -> WorkItem | None:
        """
        Get a workitem by UID.

        Args:
            uid: The UID of the workitem.

        Returns:
            The workitem, or None if not found.

        """
        # TODO: Implement database retrieval
        return local_store.get(uid)

    def update(self, workitem: WorkItem) -> WorkItem:
        """
        Update a workitem.

        Args:
            workitem: The workitem to update.

        Returns:
            The updated workitem.

        """
        if not workitem.uid:
            print("No UID in change/update workitem")
        if stored_workitem := local_store[workitem.uid]:
            if change_ds := workitem.ds:
                if stored_ds := stored_workitem.ds:
                    stored_ds.update(change_ds)
                else:
                    print(f"Unable to find dataset in stored workitem {workitem.uid}")
            else:
                print("No Change Dataset in update")
        else:
            print(f"Unable to find stored workitem with uid: {workitem.uid}")

        return local_store[workitem.uid]

    def delete(self, uid: str) -> bool:
        """
        Delete a workitem.

        Args:
            uid: The UID of the workitem.

        Returns:
            True if deleted, False otherwise.

        """
        # TODO: Implement database deletion
        del local_store[uid]
        return True

    def cancel(self, uid: str, cancel_workitem: WorkItem) -> bool:
        """
        Cancel a workitem.

        Args:
            uid: The UID of the workitem.
            cancel_workitem: The workitem to cancel

        Returns:
            True if Canceled, False otherwise.

        """
        # TODO: Implement database deletion
        stored_workitem = local_store[uid]
        stored_workitem.updated_at = datetime.now()
        stored_workitem.status = cancel_workitem.status
        self.update(cancel_workitem)
        # del local_store[uid]
        return True

    def get_all(self) -> list[WorkItem]:
        """
        Get all workitems.

        Returns:
            A list of all workitems.

        """
        # TODO: Implement database retrieval
        return deepcopy(list(local_store.values()))

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
            match (Dataset, optional): Exact matching query elements. Defaults to None.
            include_field (list[str], optional): List of tags to include in response. Defaults to None.
            fuzzy_matching (_type_, optional): Whether to use fuzzy matching for persons name. Defaults to None.
            offset (int | None, optional): starting point of List to return (for repeated queries). Defaults to None.
            limit (int | None, optional): maximum size of returned list. Defaults to None.

        Returns:
            list[WorkItem]: _description_

        """
        # TODO: Implement database retrieval
        # A broad interpretation.  An alternative would be to provide default match criteria.
        # For example in TDW-II, the date range for the scheduled procedure step can be constrained to "today"
        """
        A ‘reasonable’ date time range (such as the rest of the current day) shall be supplied to limit
        the size of the returned result set.
        If operating in a mode where the patient is selected on the SCP,
        the SCP is permitted to over-filter the result set based upon this selection
        and return just the worklist items for the selected fraction.
        """
        self.logger.warning("Fuzzy Matching not implemented")
        if not match and not include_field and not fuzzy_matching:
            return self.get_all()

        query = match

        datasets = [x.ds for x in local_store.values()]
        matching_datasets = query_datasets(query=query, datasets=datasets)
        uid_list = [str(x.SOPInstanceUID) for x in matching_datasets]
        matching_workitem_list = [local_store[workitem_uid] for workitem_uid in uid_list]
        copy_of_workitems = deepcopy(matching_workitem_list)  # we are potentially going to be removing a lot.

        include_keywords = [keyword_for_tag(int(kw, 16)) if kw.isnumeric() else kw for kw in include_field]

        self.logger.warning(f"Includefield as keywords {include_keywords}")

        if include_field and "all" not in include_field:
            self.logger.warning(f"includefield was specified and will restrict content returned: {include_field}")
            for workitem in copy_of_workitems:
                for elem in workitem.ds:
                    # tag_as_string = f"{elem.tag:08x}"
                    if elem.keyword not in include_keywords:  # and tag_as_string not in include_field:
                        del workitem.ds[elem.keyword]
        return copy_of_workitems[offset:limit]
