"""
Serializers for DICOM+XML content type support.

Provides handlers and helpers for application/dicom+xml media type,
implementing the Native DICOM Model (PS3.19) XML format.
"""

import json
from typing import Any

import falcon
from falcon.asgi import BoundedStream
from pydicom import Dataset
from pydicom_xml import from_xml, to_xml


class DICOMXMLHandler:
    """Handler for application/dicom+xml media type."""

    def deserialize(self, stream: BoundedStream, content_type: str, content_length: int) -> Dataset:
        """
        Deserialize the request body from application/dicom+xml.

        Args:
            stream: The request body stream.
            content_type: The content type of the request.
            content_length: The length of the request body.

        Returns:
            The parsed Dataset.

        """
        body = stream.read()
        if not body:
            return Dataset()
        return from_xml(body)

    def serialize(self, media: Dataset | bytes, content_type: str) -> bytes:
        """
        Serialize the media object to application/dicom+xml.

        Args:
            media: The Dataset or pre-serialized bytes to serialize.
            content_type: The content type to serialize to.

        Returns:
            The serialized media as bytes.

        """
        if isinstance(media, Dataset):
            return to_xml(media)
        return media  # already bytes

    async def deserialize_async(self, stream: BoundedStream, content_type: str, content_length: int) -> Dataset:
        """
        Deserialize the request body from application/dicom+xml (async).

        Uses ``await stream.read()`` to consume the full body on ASGI without
        blocking the event loop.

        Args:
            stream: The request body stream.
            content_type: The content type of the request.
            content_length: The length of the request body.

        Returns:
            The parsed Dataset.

        """
        body = await stream.read()
        if not body:
            return Dataset()
        return from_xml(body)

    async def serialize_async(self, media: Dataset | bytes, content_type: str) -> bytes:
        """
        Serialize the media object to application/dicom+xml (async).

        Args:
            media: The Dataset or pre-serialized bytes to serialize.
            content_type: The content type to serialize to.

        Returns:
            The serialized media as bytes.

        """
        return self.serialize(media, content_type)


SUPPORTED_DICOM_MEDIA_TYPES = ["application/dicom+json", "application/dicom+xml"]


def negotiate_content_type(req: falcon.Request) -> str:
    """
    Determine response content type from Accept header.

    Defaults to application/dicom+json if no preference or unsupported type requested.

    Args:
        req: The incoming Falcon request.

    Returns:
        The negotiated content type string.

    """
    preferred = req.client_prefers(SUPPORTED_DICOM_MEDIA_TYPES)
    return preferred or "application/dicom+json"


def serialize_dataset(ds: Dataset, content_type: str) -> tuple[bytes | str, str]:
    """
    Serialize a Dataset to the negotiated format.

    Args:
        ds: The pydicom Dataset to serialize.
        content_type: The negotiated content type (json or xml).

    Returns:
        A tuple of (serialized_data, content_type).

    """
    if "xml" in content_type:
        return to_xml(ds), "application/dicom+xml"
    return ds.to_json(), "application/dicom+json"


def serialize_dataset_list(datasets: list[Dataset], content_type: str) -> tuple[bytes | str, str]:
    """
    Serialize a list of Datasets to the negotiated format.

    For JSON: single JSON array of DICOM JSON objects.
    For XML: each Dataset is serialized as a standalone XML document,
    separated by newlines. Note: per PS3.18, multiple XML results should
    use multipart/related framing. This simplified concatenation works
    for single-result responses. Full multipart support is a future enhancement.

    Args:
        datasets: List of pydicom Datasets to serialize.
        content_type: The negotiated content type (json or xml).

    Returns:
        A tuple of (serialized_data, content_type).

    """
    if "xml" in content_type:
        if not datasets:
            return b"", "application/dicom+xml"
        xml_parts = [to_xml(ds) for ds in datasets]
        return b"\n".join(xml_parts), "application/dicom+xml"
    list_of_json = [ds.to_json() for ds in datasets]
    return "[" + ",".join(list_of_json) + "]", "application/dicom+json"


def deserialize_request_body(body: bytes, content_type: str | None) -> dict[str, Any] | Dataset:
    """
    Deserialize request body based on content type.

    Args:
        body: Raw request body bytes.
        content_type: The Content-Type header value.

    Returns:
        A dict for JSON content types, a Dataset for XML content types.

    """
    if content_type and "xml" in content_type:
        return from_xml(body) if body else Dataset()
    return json.loads(body) if body else {}
