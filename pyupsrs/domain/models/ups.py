"""Domain models for UPS workitems and related concepts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
from pydicom.uid import UID


class WorkItemStatus(Enum):
    """Status values for UPS workitems."""

    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


@dataclass
class WorkItem(Dataset):
    """A UPS workitem."""

    status: WorkItemStatus = WorkItemStatus.SCHEDULED  # Procedure Step State
    # These aren't part of the UPS definition, but they could prove to be useful
    # for logging and tracking purposes
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None

    # Get the rest using pydicom.dataset.Dataset
    #
    # scheduled_start_time: Optional[datetime] = None
    # scheduled_end_time: Optional[datetime] = None
    # patient_name: Optional[str] = None
    # patient_id: Optional[str] = None
    # accession_number: Optional[str] = None

    # These aren't real work item/ UPS scheduled procedure step properties...
    # procedure_step_type: Optional[str] = None
    # procedure_code: Optional[str] = None

    @property
    def uid(self) -> str:
        """
        Get the UID string.

        Returns:
            str: The UID value

        """
        return str(self.get("SOPInstanceUID", ""))

    @uid.setter
    def uid(self, value: str) -> None:
        """
        Set the UID string.

        Args:
            value: The UID to set

        """
        _uid = UID(value)
        if _uid.is_valid:
            self.SOPInstanceUID = value
        else:
            raise InvalidDicomError("Not a valid UID: {_uid}")

    def update_status(self, new_status: WorkItemStatus) -> None:
        """
        Update the status of the workitem.

        Args:
            new_status: The new status.

        """
        self.status = new_status
        self.ProcedureStepState = new_status
        self.updated_at = datetime.now()


@dataclass
class Subscription:
    """A subscription to a UPS workitem."""

    workitem_uid: str
    subscriber_uid: str
    created_at: datetime = field(default_factory=datetime.now)
    deletion_lock: bool = False
    contact_uri: Optional[str] = None
