"""Domain models for UPS workitems and related concepts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
from pydicom.uid import UID

GLOBAL_SUBSCRIPTION_UID = "1.2.840.10008.5.1.4.34.5"

FILTERED_SUBSCRIPTION_UID = "1.2.840.10008.5.1.4.34.5.1"


class WorkItemStatus(Enum):
    """Status values for UPS workitems."""

    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"

    @classmethod
    def from_string(cls, status_string: str) -> "WorkItemStatus":
        """
        Convert a string to the corresponding enum value.

        Args:
            status_string: The string to convert

        Returns:
            The enum value

        Raises:
            ValueError: If the string doesn't match any enum value

        """
        for status in cls:
            if status.value == status_string:
                return status
        raise ValueError(f"No enum value matches '{status_string}'")


@dataclass
class WorkItem:
    """A UPS workitem container.  Has a Dataset."""

    status: WorkItemStatus = WorkItemStatus.SCHEDULED  # Procedure Step State
    # These aren't part of the UPS definition, but they could prove to be useful
    # for logging and tracking purposes
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    transaction_uid: str = field(default=None)
    ds: Dataset = field(default_factory=Dataset)

    def __init__(self, ds: Dataset = None) -> None:
        """
        Build WorkItem from existing Dataset.

        Args:
            ds (Dataset, optional): A pydicom dataset representing a UPS. Defaults to None.

        """
        self.ds = ds
        self.created_at = datetime.now()
        self.updated_at = self.created_at
        self.transaction_uid = None
        # if self.ds:
        #     if hasattr(ds, "AffectedSOPInstanceUID") and str(ds["AffectedSOPInstanceUID"]):
        #         self.uid = str(ds["AffectedSOPInstanceUID"])
        #     elif hasattr(ds, "SOPInstanceUID") and str(ds["SOPInstanceUID"]):
        #         self.uid = str(ds["SOPInstanceUID"])

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
        return self.ds.get("SOPInstanceUID", None) or self.ds.get("AffectedSOPInstanceUID", None)

    @uid.setter
    def uid(self, value: str) -> None:
        """
        Set the UID string.

        Args:
            value: The UID to set

        """
        _uid = UID(value)
        if _uid.is_valid:
            self.ds.SOPInstanceUID = value
            self.ds.AffectedSOPInstanceUID = value
        else:
            raise InvalidDicomError("Not a valid UID: {_uid}")

    def update_procedure_step_status(self, new_status: WorkItemStatus) -> None:
        """
        Update the status of the workitem.

        Args:
            new_status: The new status.

        """
        self.status = new_status
        self.ds.ProcedureStepState = new_status.value
        self.updated_at = datetime.now()


@dataclass(frozen=True)
class Subscription:
    """A subscription to a UPS workitem."""

    workitem_uid: str  # might be GLOBAL or FILTERED Subscription (well known) UID
    ae_title: str
    created_at: datetime = field(default_factory=datetime.now)
    deletion_lock: bool = False
    contact_uri: str | None = None
    filter: Dataset | None = field(hash=False, default=None)
    suspended: bool = False  # This implies that to suspend, a new subscription has to be created and the old one deleted
