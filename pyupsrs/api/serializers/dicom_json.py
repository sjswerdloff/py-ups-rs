"""Serializers for converting between DICOM+JSON and internal models."""

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
    return workitem.ds.to_json_dict()


def deserialize_workitem(dicom_json: dict[str, Any]) -> WorkItem:
    """
    Deserialize DICOM+JSON to a WorkItem.

    Args:
        dicom_json: The DICOM+JSON representation.

    Returns:
        The deserialized WorkItem.

    """
    ds = dataset.Dataset.from_json(dicom_json)
    return WorkItem(ds=ds)
