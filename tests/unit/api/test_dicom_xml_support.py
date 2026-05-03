"""
Unit tests for DICOM XML support in workitems resources.

Tests verify:
- Content negotiation selects correct media type from Accept header
- DICOMXMLHandler serializes/deserializes Datasets correctly
- serialize_dataset and serialize_dataset_list produce correct output per content type
- deserialize_request_body handles both JSON and XML content types
- Round-trips: JSON to XML and XML to JSON are consistent
"""

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydicom import Dataset
from pydicom_xml import from_xml, to_xml

from pyupsrs.api.serializers.dicom_xml import (
    SUPPORTED_DICOM_MEDIA_TYPES,
    DICOMXMLHandler,
    deserialize_request_body,
    negotiate_content_type,
    serialize_dataset,
    serialize_dataset_list,
)

if TYPE_CHECKING:
    from pyupsrs.api.resources.workitems import DICOMJSONHandler

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_dataset() -> Dataset:
    """Return a minimal pydicom Dataset with a few attributes."""
    ds = Dataset()
    ds.file_meta = Dataset()
    ds.PatientName = "Test^Patient"
    ds.PatientID = "TEST-001"
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    return ds


@pytest.fixture()
def xml_handler() -> DICOMXMLHandler:
    """Return a fresh DICOMXMLHandler instance."""
    return DICOMXMLHandler()


def _make_accept_request(accept: str) -> MagicMock:
    """Build a minimal Falcon Request mock that responds to client_prefers."""
    req = MagicMock()

    def _client_prefers(types: list[str]) -> str | None:
        for offered in types:
            if offered in accept:
                return offered
        return None

    req.client_prefers.side_effect = _client_prefers
    return req


# ---------------------------------------------------------------------------
# negotiate_content_type
# ---------------------------------------------------------------------------


class TestNegotiateContentType:
    """Tests for negotiate_content_type helper."""

    def test_json_accept_returns_json(self) -> None:
        """Contract: Accept application/dicom+json returns JSON content type."""
        req = _make_accept_request("application/dicom+json")
        result = negotiate_content_type(req)
        assert result == "application/dicom+json"

    def test_xml_accept_returns_xml(self) -> None:
        """Contract: Accept application/dicom+xml returns XML content type."""
        req = _make_accept_request("application/dicom+xml")
        result = negotiate_content_type(req)
        assert result == "application/dicom+xml"

    def test_no_accept_defaults_to_json(self) -> None:
        """Contract: Missing or unsupported Accept header defaults to JSON."""
        req = MagicMock()
        req.client_prefers.return_value = None
        result = negotiate_content_type(req)
        assert result == "application/dicom+json"

    def test_unsupported_accept_defaults_to_json(self) -> None:
        """Contract: An unsupported Accept media type defaults to JSON."""
        req = _make_accept_request("text/html")
        result = negotiate_content_type(req)
        assert result == "application/dicom+json"

    def test_supported_media_types_constant(self) -> None:
        """Contract: SUPPORTED_DICOM_MEDIA_TYPES includes both JSON and XML."""
        assert "application/dicom+json" in SUPPORTED_DICOM_MEDIA_TYPES
        assert "application/dicom+xml" in SUPPORTED_DICOM_MEDIA_TYPES


# ---------------------------------------------------------------------------
# DICOMXMLHandler
# ---------------------------------------------------------------------------


class TestDICOMXMLHandler:
    """Tests for DICOMXMLHandler serialization and deserialization."""

    def test_serialize_dataset_returns_bytes(self, xml_handler: DICOMXMLHandler, simple_dataset: Dataset) -> None:
        """Contract: serialize returns bytes for a Dataset."""
        result = xml_handler.serialize(simple_dataset, "application/dicom+xml")
        assert isinstance(result, bytes)

    def test_serialize_dataset_is_valid_xml(self, xml_handler: DICOMXMLHandler, simple_dataset: Dataset) -> None:
        """Contract: serialized bytes are parseable as DICOM XML."""
        xml_bytes = xml_handler.serialize(simple_dataset, "application/dicom+xml")
        # If this doesn't raise, the XML is valid DICOM XML
        recovered = from_xml(xml_bytes)
        assert isinstance(recovered, Dataset)

    def test_serialize_bytes_passthrough(self, xml_handler: DICOMXMLHandler) -> None:
        """Contract: serialize passes pre-serialized bytes through unchanged."""
        raw = b"<NativeDicomModel/>"
        result = xml_handler.serialize(raw, "application/dicom+xml")
        assert result is raw

    def test_deserialize_returns_dataset(self, xml_handler: DICOMXMLHandler, simple_dataset: Dataset) -> None:
        """Contract: deserialize returns a Dataset from valid XML bytes."""
        xml_bytes = to_xml(simple_dataset)
        stream = MagicMock()
        stream.read.return_value = xml_bytes
        result = xml_handler.deserialize(stream, "application/dicom+xml", len(xml_bytes))
        assert isinstance(result, Dataset)

    def test_deserialize_preserves_patient_name(self, xml_handler: DICOMXMLHandler, simple_dataset: Dataset) -> None:
        """Contract: deserialize round-trip preserves PatientName attribute."""
        xml_bytes = to_xml(simple_dataset)
        stream = MagicMock()
        stream.read.return_value = xml_bytes
        result = xml_handler.deserialize(stream, "application/dicom+xml", len(xml_bytes))
        assert str(result.PatientName) == "Test^Patient"

    def test_deserialize_empty_body_returns_empty_dataset(self, xml_handler: DICOMXMLHandler) -> None:
        """Contract: deserialize with empty body returns an empty Dataset."""
        stream = MagicMock()
        stream.read.return_value = b""
        result = xml_handler.deserialize(stream, "application/dicom+xml", 0)
        assert isinstance(result, Dataset)

    @pytest.mark.asyncio
    async def test_deserialize_async_matches_sync(self, xml_handler: DICOMXMLHandler, simple_dataset: Dataset) -> None:
        """Contract: async deserialize returns same result as sync."""
        xml_bytes = to_xml(simple_dataset)
        stream = MagicMock()
        stream.read.return_value = xml_bytes
        sync_result = xml_handler.deserialize(stream, "application/dicom+xml", len(xml_bytes))

        # deserialize_async uses ``await stream.read()``, so stream must be an AsyncMock
        stream2 = AsyncMock()
        stream2.read.return_value = xml_bytes
        async_result = await xml_handler.deserialize_async(stream2, "application/dicom+xml", len(xml_bytes))

        assert str(sync_result.PatientName) == str(async_result.PatientName)

    @pytest.mark.asyncio
    async def test_serialize_async_matches_sync(self, xml_handler: DICOMXMLHandler, simple_dataset: Dataset) -> None:
        """Contract: async serialize returns same bytes as sync."""
        sync_result = xml_handler.serialize(simple_dataset, "application/dicom+xml")
        async_result = await xml_handler.serialize_async(simple_dataset, "application/dicom+xml")
        assert sync_result == async_result


# ---------------------------------------------------------------------------
# serialize_dataset
# ---------------------------------------------------------------------------


class TestSerializeDataset:
    """Tests for serialize_dataset helper."""

    def test_json_content_type_returns_str(self, simple_dataset: Dataset) -> None:
        """Contract: JSON content type returns a string."""
        data, ct = serialize_dataset(simple_dataset, "application/dicom+json")
        assert isinstance(data, str)
        assert ct == "application/dicom+json"

    def test_json_result_is_valid_json(self, simple_dataset: Dataset) -> None:
        """Contract: JSON result is parseable JSON."""
        data, _ = serialize_dataset(simple_dataset, "application/dicom+json")
        parsed = json.loads(data)
        assert isinstance(parsed, dict)

    def test_xml_content_type_returns_bytes(self, simple_dataset: Dataset) -> None:
        """Contract: XML content type returns bytes."""
        data, ct = serialize_dataset(simple_dataset, "application/dicom+xml")
        assert isinstance(data, bytes)
        assert ct == "application/dicom+xml"

    def test_xml_result_is_valid_dicom_xml(self, simple_dataset: Dataset) -> None:
        """Contract: XML result is parseable as DICOM XML."""
        data, _ = serialize_dataset(simple_dataset, "application/dicom+xml")
        recovered = from_xml(data)
        assert isinstance(recovered, Dataset)

    def test_xml_preserves_patient_id(self, simple_dataset: Dataset) -> None:
        """Contract: XML serialization preserves PatientID attribute."""
        data, _ = serialize_dataset(simple_dataset, "application/dicom+xml")
        recovered = from_xml(data)
        assert recovered.PatientID == "TEST-001"


# ---------------------------------------------------------------------------
# serialize_dataset_list
# ---------------------------------------------------------------------------


class TestSerializeDatasetList:
    """Tests for serialize_dataset_list helper."""

    def test_json_single_dataset_is_array(self, simple_dataset: Dataset) -> None:
        """Contract: JSON list serialization wraps single dataset in JSON array."""
        data, ct = serialize_dataset_list([simple_dataset], "application/dicom+json")
        assert ct == "application/dicom+json"
        parsed = json.loads(data)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_json_multiple_datasets_is_array(self, simple_dataset: Dataset) -> None:
        """Contract: JSON list serialization wraps multiple datasets in JSON array."""
        ds2 = Dataset()
        ds2.PatientName = "Second^Patient"
        ds2.PatientID = "TEST-002"
        ds2.is_implicit_VR = False
        ds2.is_little_endian = True
        data, ct = serialize_dataset_list([simple_dataset, ds2], "application/dicom+json")
        parsed = json.loads(data)
        assert len(parsed) == 2

    def test_xml_single_dataset_returns_bytes(self, simple_dataset: Dataset) -> None:
        """Contract: XML list serialization returns bytes."""
        data, ct = serialize_dataset_list([simple_dataset], "application/dicom+xml")
        assert ct == "application/dicom+xml"
        assert isinstance(data, bytes)

    def test_xml_single_dataset_is_valid_dicom_xml(self, simple_dataset: Dataset) -> None:
        """Contract: XML list result is parseable as DICOM XML."""
        data, _ = serialize_dataset_list([simple_dataset], "application/dicom+xml")
        # Single dataset → single XML document, parseable by from_xml
        recovered = from_xml(data)
        assert isinstance(recovered, Dataset)

    def test_xml_multiple_datasets_contains_all_patient_ids(self, simple_dataset: Dataset) -> None:
        """Contract: XML list of multiple datasets contains data from all datasets."""
        ds2 = Dataset()
        ds2.PatientName = "Second^Patient"
        ds2.PatientID = "TEST-002"
        ds2.is_implicit_VR = False
        ds2.is_little_endian = True
        data, _ = serialize_dataset_list([simple_dataset, ds2], "application/dicom+xml")
        # Both patient IDs should appear in the concatenated output
        assert b"TEST-001" in data
        assert b"TEST-002" in data

    def test_empty_list_json(self) -> None:
        """Contract: Empty list produces empty JSON array."""
        data, ct = serialize_dataset_list([], "application/dicom+json")
        assert ct == "application/dicom+json"
        parsed = json.loads(data)
        assert parsed == []

    def test_empty_list_xml(self) -> None:
        """Contract: Empty list produces empty bytes for XML."""
        data, ct = serialize_dataset_list([], "application/dicom+xml")
        assert ct == "application/dicom+xml"
        assert data == b""


# ---------------------------------------------------------------------------
# deserialize_request_body
# ---------------------------------------------------------------------------


class TestDeserializeRequestBody:
    """Tests for deserialize_request_body helper."""

    def test_json_content_type_returns_dict(self) -> None:
        """Contract: JSON content type returns a dict."""
        payload: dict[str, Any] = {"00100020": {"vr": "LO", "Value": ["TEST-001"]}}
        body = json.dumps(payload).encode()
        result = deserialize_request_body(body, "application/dicom+json")
        assert isinstance(result, dict)
        assert "00100020" in result

    def test_xml_content_type_returns_dataset(self, simple_dataset: Dataset) -> None:
        """Contract: XML content type returns a Dataset."""
        xml_bytes = to_xml(simple_dataset)
        result = deserialize_request_body(xml_bytes, "application/dicom+xml")
        assert isinstance(result, Dataset)

    def test_xml_content_type_preserves_patient_id(self, simple_dataset: Dataset) -> None:
        """Contract: XML deserialization preserves PatientID."""
        xml_bytes = to_xml(simple_dataset)
        result = deserialize_request_body(xml_bytes, "application/dicom+xml")
        assert isinstance(result, Dataset)
        assert result.PatientID == "TEST-001"

    def test_none_content_type_parses_as_json(self) -> None:
        """Contract: None content type falls back to JSON parsing."""
        payload: dict[str, Any] = {"00100020": {"vr": "LO", "Value": ["TEST-001"]}}
        body = json.dumps(payload).encode()
        result = deserialize_request_body(body, None)
        assert isinstance(result, dict)

    def test_empty_body_json_returns_empty_dict(self) -> None:
        """Contract: Empty body with JSON content type returns empty dict."""
        result = deserialize_request_body(b"", "application/dicom+json")
        assert result == {}

    def test_empty_body_xml_returns_empty_dataset(self) -> None:
        """Contract: Empty body with XML content type returns empty Dataset."""
        result = deserialize_request_body(b"", "application/dicom+xml")
        assert isinstance(result, Dataset)

    def test_xml_content_type_with_charset_suffix(self, simple_dataset: Dataset) -> None:
        """Contract: application/dicom+xml with charset suffix is recognized as XML."""
        xml_bytes = to_xml(simple_dataset)
        result = deserialize_request_body(xml_bytes, "application/dicom+xml; charset=utf-8")
        assert isinstance(result, Dataset)


# ---------------------------------------------------------------------------
# DICOMJSONHandler async deserialization (regression for issue #5)
# ---------------------------------------------------------------------------


class TestDICOMJSONHandlerAsync:
    """Regression tests for DICOMJSONHandler async deserialization path."""

    @pytest.fixture()
    def json_handler(self) -> "DICOMJSONHandler":
        """Return a fresh DICOMJSONHandler instance."""
        from pyupsrs.api.resources.workitems import DICOMJSONHandler  # local import avoids circular import

        return DICOMJSONHandler()

    @pytest.mark.asyncio
    async def test_deserialize_async_returns_dict_for_valid_json(self, json_handler: "DICOMJSONHandler") -> None:
        """Contract: deserialize_async returns a dict for valid DICOM JSON body."""
        payload: dict[str, Any] = {"00100020": {"vr": "LO", "Value": ["PATIENT-001"]}}
        body = json.dumps(payload).encode()

        # deserialize_async uses ``await stream.read()``, so stream must be an AsyncMock
        stream = AsyncMock()
        stream.read.return_value = body

        result = await json_handler.deserialize_async(stream, "application/dicom+json", len(body))

        assert isinstance(result, dict)
        assert "00100020" in result
        assert result["00100020"]["Value"] == ["PATIENT-001"]

    @pytest.mark.asyncio
    async def test_deserialize_async_returns_empty_dict_for_empty_body(self, json_handler: "DICOMJSONHandler") -> None:
        """Contract: deserialize_async returns empty dict when body is empty."""
        stream = AsyncMock()
        stream.read.return_value = b""

        result = await json_handler.deserialize_async(stream, "application/dicom+json", 0)

        assert result == {}

    @pytest.mark.asyncio
    async def test_deserialize_async_matches_sync_result(self, json_handler: "DICOMJSONHandler") -> None:
        """Contract: async deserialize produces the same dict as sync deserialize."""
        payload: dict[str, Any] = {
            "00080016": {"vr": "UI", "Value": ["1.2.840.10008.5.1.4.34.6.1"]},
            "00100020": {"vr": "LO", "Value": ["SYNC-ASYNC-MATCH"]},
        }
        body = json.dumps(payload).encode()

        # Sync path
        sync_stream = MagicMock()
        sync_stream.read.return_value = body
        sync_result = json_handler.deserialize(sync_stream, "application/dicom+json", len(body))

        # Async path (uses await stream.read())
        async_stream = AsyncMock()
        async_stream.read.return_value = body
        async_result = await json_handler.deserialize_async(async_stream, "application/dicom+json", len(body))

        assert sync_result == async_result
