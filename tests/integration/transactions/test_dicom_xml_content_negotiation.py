"""
Integration tests for DICOM XML content negotiation in UPS-RS endpoints.

Tests verify:
- GET /workitems with Accept: application/dicom+xml returns XML content type
- GET /workitems with Accept: application/dicom+json returns JSON (existing behavior preserved)
- GET /workitems with no Accept header defaults to JSON
- GET /workitems/{uid} with Accept: application/dicom+xml returns XML
- POST /workitems with Content-Type: application/dicom+xml body is parsed correctly
- XML response is valid DICOM XML parseable by from_xml()
- Round-trip: create workitem with JSON, retrieve with XML Accept header, parse XML response
"""

import json
from typing import Any

import pytest
from falcon.testing.client import TestClient
from pydicom import Dataset
from pydicom.uid import generate_uid
from pydicom_xml import from_xml, to_xml

from tests.integration.transactions.test_workitem_transactions import create_workitem_helper, retrieve_workitem_helper


def _extract_sop_instance_uid_from_workitem(workitem_dict: dict[str, Any]) -> str:
    """Extract SOP Instance UID from a DICOM JSON workitem dict."""
    return workitem_dict["00080018"]["Value"][0]


@pytest.fixture()
def base_workitem_json() -> dict[str, Any]:
    """Return a minimal valid UPS workitem as a DICOM JSON dict with a fresh UID."""
    from datetime import datetime, timedelta

    return {
        "00080016": {"vr": "UI", "Value": ["1.2.840.10008.5.1.4.34.6.1"]},
        "00080018": {"vr": "UI", "Value": [str(generate_uid())]},
        "00080054": {"vr": "AE", "Value": ["TESTSTATION"]},
        "00080056": {"vr": "CS", "Value": ["READY"]},
        "00100010": {"vr": "PN", "Value": [{"Alphabetic": "XML^TEST^PATIENT"}]},
        "00100020": {"vr": "LO", "Value": ["XML-TEST-001"]},
        "00100030": {"vr": "DA", "Value": ["20230101"]},
        "00404041": {"vr": "CS", "Value": ["READY"]},
        "00404005": {"vr": "DT", "Value": [datetime.now().strftime("%Y%m%d%H%M%S")]},
        "00404010": {"vr": "DT", "Value": [(datetime.now() + timedelta(hours=1)).strftime("%Y%m%d%H%M%S")]},
        "00404025": {
            "vr": "SQ",
            "Value": [
                {
                    "00080100": {"vr": "SH", "Value": ["XML_STATION"]},
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},
                    "00080104": {"vr": "LO", "Value": ["XML Test Station"]},
                }
            ],
        },
        "00404026": {
            "vr": "SQ",
            "Value": [
                {
                    "00080100": {"vr": "SH", "Value": ["STATION_CLASS"]},
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},
                    "00080104": {"vr": "LO", "Value": ["Test Station Class"]},
                }
            ],
        },
        "00404027": {
            "vr": "SQ",
            "Value": [
                {
                    "00080100": {"vr": "SH", "Value": ["TEST_LOCATION"]},
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},
                    "00080104": {"vr": "LO", "Value": ["Test Location"]},
                }
            ],
        },
        "00404018": {
            "vr": "SQ",
            "Value": [
                {
                    "00080100": {"vr": "SH", "Value": ["TEST_WORKITEM"]},
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},
                    "00080104": {"vr": "LO", "Value": ["Test Workitem"]},
                }
            ],
        },
        "00741000": {"vr": "CS", "Value": ["SCHEDULED"]},
    }


class TestGetWorkitemsXmlAccept:
    """Tests for GET /workitems with XML Accept header."""

    def test_get_workitems_xml_accept_returns_xml_content_type(
        self, client: TestClient, base_workitem_json: dict[str, Any]
    ) -> None:
        """Contract: GET /workitems with XML Accept returns application/dicom+xml content type."""
        # First create a workitem so there is something to retrieve
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get("/workitems", headers={"Accept": "application/dicom+xml"})

        assert resp.status_code == 200
        assert "application/dicom+xml" in resp.headers.get("content-type", "")

    def test_get_workitems_xml_accept_body_is_valid_dicom_xml(
        self, client: TestClient, base_workitem_json: dict[str, Any]
    ) -> None:
        """Contract: GET /workitems with XML Accept returns multipart/related with parseable parts."""
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get("/workitems", headers={"Accept": "application/dicom+xml"})

        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "multipart/related" in ct
        # Extract boundary and parse first part
        boundary = ct.split("boundary=")[1]
        parts = resp.content.split(f"--{boundary}".encode("utf-8"))
        xml_parts = [p for p in parts[1:-1] if p.strip()]
        assert len(xml_parts) >= 1
        xml_body = xml_parts[0].split(b"\r\n\r\n", 1)[1].strip()
        ds = from_xml(xml_body)
        assert isinstance(ds, Dataset)

    def test_get_workitems_json_accept_returns_json_content_type(
        self, client: TestClient, base_workitem_json: dict[str, Any]
    ) -> None:
        """Contract: GET /workitems with JSON Accept still returns JSON (existing behavior)."""
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get("/workitems", headers={"Accept": "application/dicom+json"})

        assert resp.status_code == 200
        assert "application/dicom+json" in resp.headers.get("content-type", "")

    def test_get_workitems_json_accept_body_is_valid_json(
        self, client: TestClient, base_workitem_json: dict[str, Any]
    ) -> None:
        """Contract: GET /workitems with JSON Accept returns parseable JSON array."""
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get("/workitems", headers={"Accept": "application/dicom+json"})

        assert resp.status_code == 200
        parsed = json.loads(resp.text)
        assert isinstance(parsed, list)

    def test_get_workitems_no_accept_defaults_to_json(self, client: TestClient, base_workitem_json: dict[str, Any]) -> None:
        """Contract: GET /workitems with no Accept header defaults to JSON."""
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get("/workitems")

        assert resp.status_code == 200
        assert "application/dicom+json" in resp.headers.get("content-type", "")


class TestGetWorkitemXmlAccept:
    """Tests for GET /workitems/{uid} with XML Accept header."""

    def test_get_workitem_xml_accept_returns_xml_content_type(
        self, client: TestClient, base_workitem_json: dict[str, Any]
    ) -> None:
        """Contract: GET /workitems/{uid} with XML Accept returns application/dicom+xml."""
        uid = _extract_sop_instance_uid_from_workitem(base_workitem_json)
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get(f"/workitems/{uid}", headers={"Accept": "application/dicom+xml"})

        assert resp.status_code == 200
        assert "application/dicom+xml" in resp.headers.get("content-type", "")

    def test_get_workitem_xml_accept_body_is_valid_dicom_xml(
        self, client: TestClient, base_workitem_json: dict[str, Any]
    ) -> None:
        """Contract: GET /workitems/{uid} with XML Accept returns parseable DICOM XML."""
        uid = _extract_sop_instance_uid_from_workitem(base_workitem_json)
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get(f"/workitems/{uid}", headers={"Accept": "application/dicom+xml"})

        assert resp.status_code == 200
        ds = from_xml(resp.content)
        assert isinstance(ds, Dataset)

    def test_get_workitem_json_accept_still_works(self, client: TestClient, base_workitem_json: dict[str, Any]) -> None:
        """Contract: GET /workitems/{uid} with JSON Accept still returns JSON."""
        uid = _extract_sop_instance_uid_from_workitem(base_workitem_json)
        create_workitem_helper(client, base_workitem_json)

        resp = retrieve_workitem_helper(client, uid)

        assert resp.status_code == 200
        assert "application/dicom+json" in resp.headers.get("content-type", "")
        parsed = json.loads(resp.text)
        assert isinstance(parsed, dict)


class TestPostWorkitemXmlBody:
    """Tests for POST /workitems with XML Content-Type."""

    def test_post_workitem_xml_body_returns_201(self, client: TestClient, base_workitem_json: dict[str, Any]) -> None:
        """Contract: POST /workitems with XML body creates a workitem (HTTP 201)."""
        # Build a Dataset from the JSON fixture, then convert to XML
        from pydicom.dataset import Dataset as PydcmDataset

        ds = PydcmDataset.from_json(base_workitem_json)
        xml_body = to_xml(ds)

        resp = client.simulate_post(
            "/workitems",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )

        assert resp.status_code == 201

    def test_post_workitem_xml_body_stores_retrievable_workitem(
        self, client: TestClient, base_workitem_json: dict[str, Any]
    ) -> None:
        """Contract: Workitem POSTed with XML body can be retrieved with JSON Accept."""
        uid = _extract_sop_instance_uid_from_workitem(base_workitem_json)
        from pydicom.dataset import Dataset as PydcmDataset

        ds = PydcmDataset.from_json(base_workitem_json)
        xml_body = to_xml(ds)

        client.simulate_post(
            "/workitems",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )

        # Should be retrievable via JSON Accept
        resp = retrieve_workitem_helper(client, uid)
        assert resp.status_code == 200


class TestRoundTripXmlJson:
    """Round-trip tests: create with JSON, retrieve with XML; and vice versa."""

    def test_create_json_retrieve_xml_round_trip(self, client: TestClient, base_workitem_json: dict[str, Any]) -> None:
        """Contract: Workitem created with JSON can be retrieved and parsed as valid DICOM XML."""
        uid = _extract_sop_instance_uid_from_workitem(base_workitem_json)
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get(f"/workitems/{uid}", headers={"Accept": "application/dicom+xml"})

        assert resp.status_code == 200
        ds = from_xml(resp.content)
        assert isinstance(ds, Dataset)
        # PatientID should survive the round-trip
        assert ds.PatientID == "XML-TEST-001"

    def test_create_json_retrieve_list_as_xml(self, client: TestClient, base_workitem_json: dict[str, Any]) -> None:
        """Contract: Workitem list created with JSON can be retrieved as multipart/related XML."""
        create_workitem_helper(client, base_workitem_json)

        resp = client.simulate_get("/workitems", headers={"Accept": "application/dicom+xml"})

        assert resp.status_code == 200
        assert "multipart/related" in resp.headers.get("content-type", "")
        # Extract boundary and parse first part
        ct = resp.headers["content-type"]
        boundary = ct.split("boundary=")[1]
        parts = resp.content.split(f"--{boundary}".encode("utf-8"))
        xml_parts = [p for p in parts[1:-1] if p.strip()]
        assert len(xml_parts) >= 1
        # Parse the XML body from the first part (after headers)
        xml_body = xml_parts[0].split(b"\r\n\r\n", 1)[1].strip()
        ds = from_xml(xml_body)
        assert isinstance(ds, Dataset)

    def test_create_xml_retrieve_xml_round_trip(self, client: TestClient, base_workitem_json: dict[str, Any]) -> None:
        """Contract: Workitem POSTed with XML body can be retrieved as XML with same patient data."""
        uid = _extract_sop_instance_uid_from_workitem(base_workitem_json)
        from pydicom.dataset import Dataset as PydcmDataset

        ds = PydcmDataset.from_json(base_workitem_json)
        xml_body = to_xml(ds)

        client.simulate_post(
            "/workitems",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )

        resp = client.simulate_get(f"/workitems/{uid}", headers={"Accept": "application/dicom+xml"})
        assert resp.status_code == 200
        retrieved_ds = from_xml(resp.content)
        assert retrieved_ds.PatientID == "XML-TEST-001"


class TestInvalidRequestBodyReturns400:
    """Tests for invalid request bodies returning HTTP 400 instead of 500."""

    def test_post_workitem_invalid_json_returns_400(self, client: TestClient) -> None:
        """Contract: POST /workitems with malformed JSON body returns 400 Bad Request."""
        resp = client.simulate_post(
            "/workitems",
            body=b"{not valid json}",
            headers={"Content-Type": "application/dicom+json"},
        )
        assert resp.status_code == 400

    def test_post_workitem_invalid_xml_returns_400(self, client: TestClient) -> None:
        """Contract: POST /workitems with malformed XML body returns 400 Bad Request."""
        resp = client.simulate_post(
            "/workitems",
            body=b"<unclosed-tag>this is not valid XML",
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert resp.status_code == 400

    def test_post_workitem_truncated_json_returns_400(self, client: TestClient) -> None:
        """Contract: POST /workitems with truncated JSON body returns 400 Bad Request."""
        resp = client.simulate_post(
            "/workitems",
            body=b'{"00080018": {"vr": "UI"',  # truncated, no closing braces
            headers={"Content-Type": "application/dicom+json"},
        )
        assert resp.status_code == 400
