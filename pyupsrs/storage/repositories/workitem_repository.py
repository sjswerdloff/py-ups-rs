"""Repository for accessing UPS workitems."""

from copy import deepcopy
from typing import Optional

from pyupsrs.domain.models.ups import WorkItem

local_store: dict[str, WorkItem] = {}


class WorkItemRepository:
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

    def get_by_uid(self, uid: str) -> Optional[WorkItem]:
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
        # TODO: Implement database update
        return local_store[workitem.uid].ds.update(workitem.ds)

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

    def get_all(self) -> list[WorkItem]:
        """
        Get all workitems.

        Returns:
            A list of all workitems.

        """
        # TODO: Implement database retrieval
        return deepcopy(local_store)
