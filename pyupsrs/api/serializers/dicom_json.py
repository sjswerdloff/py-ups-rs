"""Serializers for converting between DICOM+JSON and internal models."""

from datetime import datetime
from typing import Any

from pydicom import dataset

from pyupsrs.domain.models.ups import WorkItem


def serialize_workitem(workitem: WorkItem) -> dict[str, Any]:
    """
    Serialize a WorkItem to DICOM+JSON format.

    Args:
        workitem: The WorkItem to serialize.

    Returns:
        The serialized DICOM+JSON representation.

    """
    return workitem.to_json_dict()


def deserialize_workitem(dicom_json: dict[str, Any]) -> WorkItem:
    """
    Deserialize DICOM+JSON to a WorkItem.

    Args:
        dicom_json: The DICOM+JSON representation.

    Returns:
        The deserialized WorkItem.

    """
    workitem = dataset.Dataset.from_json(dicom_json)
    workitem.uid = workitem.SOPInstanceUID
    workitem.status = workitem.ProcedureStepState
    workitem.created_at = datetime.now()
    return workitem
