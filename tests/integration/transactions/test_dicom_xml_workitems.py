"""
Integration tests for XML content negotiation in UPS-RS workitem operations.

Verifies that the server correctly handles ``application/dicom+xml`` for:
- GET a single workitem (Accept: application/dicom+xml)
- GET workitem list / search (Accept: application/dicom+xml → multipart/related)
- POST a new workitem with an XML body (Content-Type: application/dicom+xml)
- Round-trip: POST as JSON, GET as XML, verify patient data survives
- PUT update workitem with XML body (Content-Type: application/dicom+xml)
- PUT state change with XML body (Content-Type: application/dicom+xml)
- Error paths in workitem service

All tests use the ``client`` and ``created_workitem_uid`` fixtures from conftest.py.

Note on known server limitations:
- WorkItemStateResource.on_put reads the body with ``json.loads()`` directly and
  does NOT go through content-type negotiation, so XML change-state requests are
  not supported and are marked xfail.
- WorkItemResource.on_put (workitem update) similarly hard-codes JSON parsing.
"""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any

import pytest
from falcon.testing.client import TestClient
from pydicom import Dataset
from pydicom.uid import generate_uid
from pydicom_xml import dataset_to_xml, from_xml, to_xml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_xml_workitem(patient_id: str = "TEST-XML-001", patient_name: str = "TEST^XML^PATIENT") -> tuple[bytes, str]:
    """
    Build a minimal valid UPS workitem as DICOM XML bytes.

    Args:
        patient_id: Patient ID to embed in the workitem.
        patient_name: Patient name (DICOM PN format) to embed.

    Returns:
        A tuple of (xml_bytes, sop_instance_uid) for the created workitem.

    """
    uid = str(generate_uid())
    ds = Dataset()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.34.6.1"  # UPS Push SOP Class
    ds.SOPInstanceUID = uid
    ds.RetrieveAETitle = "TESTSTATION"
    ds.InstanceAvailability = "READY"
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "20230101"
    ds.InputReadinessState = "READY"
    ds.ScheduledProcedureStepStartDateTime = datetime.now().strftime("%Y%m%d%H%M%S")
    ds.ProcedureStepState = "SCHEDULED"
    return to_xml(ds), uid


# ---------------------------------------------------------------------------
# GET single workitem as XML
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetWorkitemAsXml:
    """GET /workitems/{uid} with Accept: application/dicom+xml returns DICOM XML."""

    def test_get_workitem_returns_200_with_xml_accept(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: GET with Accept application/dicom+xml returns HTTP 200."""
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200

    def test_get_workitem_content_type_is_dicom_xml(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: GET with Accept application/dicom+xml sets Content-Type to application/dicom+xml."""
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        assert "application/dicom+xml" in result.headers.get("Content-Type", "")

    def test_get_workitem_response_body_is_valid_dicom_xml(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: response body is parseable as a DICOM Dataset via from_xml."""
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        recovered = from_xml(result.content)
        assert isinstance(recovered, Dataset)

    def test_get_workitem_xml_contains_sop_instance_uid(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: parsed XML Dataset contains the expected SOPInstanceUID."""
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        recovered = from_xml(result.content)
        assert str(recovered.SOPInstanceUID) == created_workitem_uid

    def test_get_nonexistent_workitem_returns_404(self, client: TestClient) -> None:
        """Contract: GET with XML accept for missing workitem returns HTTP 404."""
        result = client.simulate_get(
            f"/workitems/{generate_uid()}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 404

    def test_get_workitem_xml_contains_patient_id_from_fixture(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: parsed XML Dataset preserves the PatientID stored during creation."""
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        recovered = from_xml(result.content)
        # The conftest fixture creates workitems with PatientID "TEST-ID-123"
        assert recovered.PatientID == "TEST-ID-123"


# ---------------------------------------------------------------------------
# GET workitem list as XML (search / multipart/related)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSearchWorkitemsAsXml:
    """GET /workitems with Accept: application/dicom+xml returns multipart/related XML."""

    def test_search_returns_200_when_workitems_exist(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: search with XML accept returns HTTP 200 when at least one workitem exists."""
        result = client.simulate_get(
            "/workitems",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200

    def test_search_content_type_is_multipart_related(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: XML list response Content-Type is multipart/related."""
        result = client.simulate_get(
            "/workitems",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        content_type = result.headers.get("Content-Type", "")
        assert "multipart/related" in content_type

    def test_search_multipart_response_contains_boundary(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: multipart/related Content-Type header includes a boundary parameter."""
        result = client.simulate_get(
            "/workitems",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        content_type = result.headers.get("Content-Type", "")
        assert "boundary=" in content_type

    def test_search_multipart_response_body_contains_dicom_xml_markup(
        self, client: TestClient, created_workitem_uid: str
    ) -> None:
        """Contract: the response body contains NativeDicomModel XML markup."""
        result = client.simulate_get(
            "/workitems",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        assert b"NativeDicomModel" in result.content

    def test_search_multipart_parts_are_parseable_as_dicom_xml(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: each multipart part body parses as a valid DICOM Dataset."""
        result = client.simulate_get(
            "/workitems",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200
        content_type = result.headers.get("Content-Type", "")
        boundary = content_type.split("boundary=")[1].strip()
        parts = result.content.split(f"--{boundary}".encode())
        # Filter out preamble and closing delimiter
        data_parts = [p for p in parts[1:-1] if p.strip()]
        assert len(data_parts) >= 1
        for part in data_parts:
            xml_body = part.split(b"\r\n\r\n", 1)[1].strip()
            recovered = from_xml(xml_body)
            assert isinstance(recovered, Dataset)

    def test_search_returns_404_when_no_workitems(self, client: TestClient) -> None:
        """Contract: search with XML accept returns 404 when no workitems match (empty store)."""
        # reset_workitem_repository fixture ensures the store is empty at test start.
        result = client.simulate_get(
            "/workitems",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 404

    def test_search_with_matching_patient_id_returns_200(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: search filtered by the fixture PatientID returns HTTP 200."""
        result = client.simulate_get(
            "/workitems?PatientID=TEST-ID-123",
            headers={"Accept": "application/dicom+xml"},
        )
        assert result.status_code == 200


# ---------------------------------------------------------------------------
# POST workitem with XML body
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPostWorkitemAsXml:
    """POST /workitems with Content-Type: application/dicom+xml creates the workitem."""

    def test_post_xml_workitem_returns_201(self, client: TestClient) -> None:
        """Contract: POST with a valid XML body and correct Content-Type returns HTTP 201."""
        xml_bytes, _uid = _build_xml_workitem()
        result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 201

    def test_post_xml_workitem_response_contains_sop_instance_uid(self, client: TestClient) -> None:
        """Contract: 201 response body (XML or JSON) contains the SOPInstanceUID of the created workitem."""
        xml_bytes, uid = _build_xml_workitem()
        result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 201
        # Response body may be XML or JSON depending on Accept header (defaulting to JSON here).
        # Verify UID appears in the raw response body either way.
        assert uid.encode() in result.content

    def test_post_xml_workitem_is_retrievable_as_json(self, client: TestClient) -> None:
        """Contract: after XML POST, the workitem is retrievable via GET as JSON."""
        xml_bytes, uid = _build_xml_workitem(patient_id="XML-POST-RETRIEVE")
        post_result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert post_result.status_code == 201

        get_result = client.simulate_get(
            f"/workitems/{uid}",
            headers={"Accept": "application/dicom+json"},
        )
        assert get_result.status_code == 200
        payload = json.loads(get_result.text)
        # PatientID tag 00100020
        assert payload["00100020"]["Value"] == ["XML-POST-RETRIEVE"]

    def test_post_xml_workitem_is_retrievable_as_xml(self, client: TestClient) -> None:
        """Contract: after XML POST, the workitem is retrievable via GET as XML."""
        xml_bytes, uid = _build_xml_workitem(patient_id="XML-POST-XML-RETRIEVE")
        post_result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert post_result.status_code == 201

        get_result = client.simulate_get(
            f"/workitems/{uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert get_result.status_code == 200
        recovered = from_xml(get_result.content)
        assert recovered.PatientID == "XML-POST-XML-RETRIEVE"

    def test_post_duplicate_xml_workitem_returns_409(self, client: TestClient) -> None:
        """Contract: POSTing an XML workitem with a duplicate UID returns HTTP 409."""
        xml_bytes, _uid = _build_xml_workitem()
        first_result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert first_result.status_code == 201

        second_result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert second_result.status_code == 409

    def test_post_empty_xml_body_returns_400(self, client: TestClient) -> None:
        """Contract: POST with an empty body and XML Content-Type returns HTTP 400."""
        result = client.simulate_post(
            "/workitems",
            body=b"",
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400

    def test_post_malformed_xml_body_returns_400(self, client: TestClient) -> None:
        """Contract: POST with syntactically invalid XML returns HTTP 400."""
        result = client.simulate_post(
            "/workitems",
            body=b"<NotValid XML>",
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# Round-trip: POST as JSON, GET as XML
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestJsonPostXmlGetRoundTrip:
    """Verify that patient data survives a JSON POST followed by an XML GET."""

    def test_json_post_xml_get_preserves_patient_id(self, client: TestClient, sample_ups_workitem: dict[str, Any]) -> None:
        """Contract: patient ID posted as JSON is present in the XML GET response."""
        workitem = deepcopy(sample_ups_workitem)
        uid = str(generate_uid())
        workitem["00080018"]["Value"] = [uid]
        workitem["00741000"] = {"vr": "CS", "Value": ["SCHEDULED"]}
        workitem["00100020"] = {"vr": "LO", "Value": ["ROUNDTRIP-PATIENT-001"]}

        post_result = client.simulate_post(
            "/workitems",
            body=json.dumps(workitem).encode("utf-8"),
            headers={"Content-Type": "application/dicom+json"},
        )
        assert post_result.status_code == 201

        get_result = client.simulate_get(
            f"/workitems/{uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert get_result.status_code == 200
        recovered = from_xml(get_result.content)
        assert recovered.PatientID == "ROUNDTRIP-PATIENT-001"

    def test_json_post_xml_get_preserves_patient_name(self, client: TestClient, sample_ups_workitem: dict[str, Any]) -> None:
        """Contract: patient name posted as JSON is present in the XML GET response."""
        workitem = deepcopy(sample_ups_workitem)
        uid = str(generate_uid())
        workitem["00080018"]["Value"] = [uid]
        workitem["00741000"] = {"vr": "CS", "Value": ["SCHEDULED"]}
        workitem["00100010"] = {"vr": "PN", "Value": [{"Alphabetic": "ROUNDTRIP^NAME"}]}

        post_result = client.simulate_post(
            "/workitems",
            body=json.dumps(workitem).encode("utf-8"),
            headers={"Content-Type": "application/dicom+json"},
        )
        assert post_result.status_code == 201

        get_result = client.simulate_get(
            f"/workitems/{uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert get_result.status_code == 200
        recovered = from_xml(get_result.content)
        assert "ROUNDTRIP" in str(recovered.PatientName)

    def test_json_post_xml_get_preserves_sop_instance_uid(
        self, client: TestClient, sample_ups_workitem: dict[str, Any]
    ) -> None:
        """Contract: SOPInstanceUID posted as JSON matches the UID in the XML GET response."""
        workitem = deepcopy(sample_ups_workitem)
        uid = str(generate_uid())
        workitem["00080018"]["Value"] = [uid]
        workitem["00741000"] = {"vr": "CS", "Value": ["SCHEDULED"]}

        post_result = client.simulate_post(
            "/workitems",
            body=json.dumps(workitem).encode("utf-8"),
            headers={"Content-Type": "application/dicom+json"},
        )
        assert post_result.status_code == 201

        get_result = client.simulate_get(
            f"/workitems/{uid}",
            headers={"Accept": "application/dicom+xml"},
        )
        assert get_result.status_code == 200
        recovered = from_xml(get_result.content)
        assert str(recovered.SOPInstanceUID) == uid

    def test_json_post_xml_search_finds_workitem(self, client: TestClient, sample_ups_workitem: dict[str, Any]) -> None:
        """Contract: workitem posted as JSON appears in the XML search results."""
        workitem = deepcopy(sample_ups_workitem)
        uid = str(generate_uid())
        workitem["00080018"]["Value"] = [uid]
        workitem["00741000"] = {"vr": "CS", "Value": ["SCHEDULED"]}
        workitem["00100020"] = {"vr": "LO", "Value": ["SEARCH-ROUNDTRIP-PATIENT"]}

        post_result = client.simulate_post(
            "/workitems",
            body=json.dumps(workitem).encode("utf-8"),
            headers={"Content-Type": "application/dicom+json"},
        )
        assert post_result.status_code == 201

        search_result = client.simulate_get(
            "/workitems",
            headers={"Accept": "application/dicom+xml"},
        )
        assert search_result.status_code == 200
        # The UID of the created workitem should appear somewhere in the multipart body
        assert uid.encode() in search_result.content


# ---------------------------------------------------------------------------
# XML POST with explicit XML Accept — response format negotiation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestXmlPostWithXmlAccept:
    """POST /workitems with XML body and Accept: application/dicom+xml negotiates XML response."""

    def test_post_xml_body_xml_accept_returns_201(self, client: TestClient) -> None:
        """Contract: POST with XML body and XML Accept header returns HTTP 201."""
        xml_bytes, _uid = _build_xml_workitem()
        result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={
                "Content-Type": "application/dicom+xml",
                "Accept": "application/dicom+xml",
            },
        )
        assert result.status_code == 201

    def test_post_xml_body_xml_accept_response_content_type_is_xml(self, client: TestClient) -> None:
        """Contract: POST with XML body and XML Accept returns Content-Type application/dicom+xml."""
        xml_bytes, _uid = _build_xml_workitem()
        result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={
                "Content-Type": "application/dicom+xml",
                "Accept": "application/dicom+xml",
            },
        )
        assert result.status_code == 201
        assert "application/dicom+xml" in result.headers.get("Content-Type", "")

    def test_post_xml_body_xml_accept_response_body_is_valid_dicom_xml(self, client: TestClient) -> None:
        """Contract: 201 response with XML accept contains a parseable DICOM XML body."""
        xml_bytes, uid = _build_xml_workitem()
        result = client.simulate_post(
            "/workitems",
            body=xml_bytes,
            headers={
                "Content-Type": "application/dicom+xml",
                "Accept": "application/dicom+xml",
            },
        )
        assert result.status_code == 201
        recovered = from_xml(result.content)
        assert isinstance(recovered, Dataset)
        assert str(recovered.SOPInstanceUID) == uid


# ---------------------------------------------------------------------------
# PUT update workitem with XML body
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestXmlPostUpdateWorkitem:
    """PUT /workitems/{uid} with Content-Type: application/dicom+xml updates the workitem."""

    def test_post_xml_update_returns_200(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: PUT with a valid XML body and correct Content-Type returns HTTP 200."""
        update_ds = Dataset()
        update_ds.ScheduledProcedureStepStartDateTime = "20250601120000"
        update_ds.ScheduledProcedureStepExpirationDateTime = "20250601130000"
        xml_body = dataset_to_xml(update_ds)

        result = client.simulate_post(
            f"/workitems/{created_workitem_uid}",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 200

    def test_post_xml_update_is_reflected_in_get(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: after XML PUT, the updated scheduled time is retrievable via GET."""
        scheduled_start = "20250701090000"
        update_ds = Dataset()
        update_ds.ScheduledProcedureStepStartDateTime = scheduled_start
        xml_body = dataset_to_xml(update_ds)

        put_result = client.simulate_post(
            f"/workitems/{created_workitem_uid}",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert put_result.status_code == 200

        get_result = client.simulate_get(
            f"/workitems/{created_workitem_uid}",
            headers={"Accept": "application/dicom+json"},
        )
        assert get_result.status_code == 200
        payload = json.loads(get_result.text)
        # ScheduledProcedureStepStartDateTime tag 00404005
        assert payload["00404005"]["Value"] == [scheduled_start]

    def test_post_xml_update_empty_body_returns_400(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: PUT with empty body and XML Content-Type returns HTTP 400."""
        result = client.simulate_post(
            f"/workitems/{created_workitem_uid}",
            body=b"",
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400

    def test_post_xml_update_malformed_xml_returns_400(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: PUT with malformed XML body and XML Content-Type returns HTTP 400."""
        result = client.simulate_post(
            f"/workitems/{created_workitem_uid}",
            body=b"<NotValidXML>",
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400

    def test_post_xml_update_nonexistent_workitem_returns_404(self, client: TestClient) -> None:
        """Contract: PUT XML update for a non-existent workitem UID returns HTTP 404."""
        update_ds = Dataset()
        update_ds.ScheduledProcedureStepStartDateTime = "20250601120000"
        xml_body = dataset_to_xml(update_ds)

        result = client.simulate_post(
            f"/workitems/{generate_uid()}",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 404

    def test_post_xml_update_strips_procedure_step_state_with_warning(
        self, client: TestClient, created_workitem_uid: str
    ) -> None:
        """Contract: PUT with ProcedureStepState in XML body returns 200 with a 299 warning header."""
        update_ds = Dataset()
        update_ds.ProcedureStepState = "IN PROGRESS"
        update_ds.ScheduledProcedureStepStartDateTime = "20250601120000"
        xml_body = dataset_to_xml(update_ds)

        result = client.simulate_post(
            f"/workitems/{created_workitem_uid}",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 200
        warning_header = result.headers.get("Warning", "")
        assert "299" in warning_header


# ---------------------------------------------------------------------------
# PUT state change with XML body
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestXmlPutStateChange:
    """PUT /workitems/{uid}/state with Content-Type: application/dicom+xml changes workitem state."""

    def test_put_xml_state_change_to_in_progress_returns_200(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: XML PUT state change to IN PROGRESS returns HTTP 200."""
        transaction_uid = str(generate_uid())
        state_ds = Dataset()
        state_ds.ProcedureStepState = "IN PROGRESS"
        state_ds.TransactionUID = transaction_uid
        xml_body = dataset_to_xml(state_ds)

        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}/state",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 200

    def test_put_xml_state_change_to_completed_returns_200(
        self, client: TestClient, in_progress_workitem_uid: tuple[str, str]
    ) -> None:
        """Contract: XML PUT state change to COMPLETED on an in-progress workitem returns HTTP 200."""
        workitem_uid, transaction_uid = in_progress_workitem_uid
        state_ds = Dataset()
        state_ds.ProcedureStepState = "COMPLETED"
        state_ds.TransactionUID = transaction_uid
        xml_body = dataset_to_xml(state_ds)

        result = client.simulate_put(
            f"/workitems/{workitem_uid}/state",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 200

    def test_put_xml_state_change_empty_body_returns_400(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: XML PUT state change with empty body returns HTTP 400."""
        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}/state",
            body=b"",
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400

    def test_put_xml_state_change_malformed_xml_returns_400(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: XML PUT state change with malformed XML body returns HTTP 400."""
        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}/state",
            body=b"<broken",
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# Error path tests for workitem service
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkitemServiceErrorPaths:
    """Error path tests verifying the workitem service returns correct status codes."""

    def test_state_change_on_nonexistent_workitem_returns_error(self, client: TestClient) -> None:
        """Contract: state change PUT on a nonexistent workitem returns an error response (404)."""
        nonexistent_uid = str(generate_uid())
        transaction_uid = str(generate_uid())
        payload = {
            "00081195": {"vr": "UI", "Value": [transaction_uid]},
            "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
        }
        result = client.simulate_put(
            f"/workitems/{nonexistent_uid}/state",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/dicom+json"},
        )
        assert result.status_code == 404

    def test_state_change_missing_transaction_uid_returns_400(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: state change PUT without TransactionUID returns HTTP 400."""
        payload = {
            "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
        }
        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}/state",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/dicom+json"},
        )
        assert result.status_code == 400

    def test_state_change_with_wrong_transaction_uid_on_claimed_workitem_returns_400(
        self, client: TestClient, in_progress_workitem_uid: tuple[str, str]
    ) -> None:
        """Contract: state change with incorrect TransactionUID on a claimed workitem returns HTTP 400."""
        workitem_uid, _correct_transaction_uid = in_progress_workitem_uid
        wrong_transaction_uid = str(generate_uid())
        payload = {
            "00081195": {"vr": "UI", "Value": [wrong_transaction_uid]},
            "00741000": {"vr": "CS", "Value": ["COMPLETED"]},
        }
        result = client.simulate_put(
            f"/workitems/{workitem_uid}/state",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/dicom+json"},
        )
        assert result.status_code == 400

    def test_xml_state_change_on_nonexistent_workitem_returns_error(self, client: TestClient) -> None:
        """Contract: XML state change PUT on a nonexistent workitem returns an error response (404)."""
        nonexistent_uid = str(generate_uid())
        state_ds = Dataset()
        state_ds.ProcedureStepState = "IN PROGRESS"
        state_ds.TransactionUID = str(generate_uid())
        xml_body = dataset_to_xml(state_ds)

        result = client.simulate_put(
            f"/workitems/{nonexistent_uid}/state",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 404

    def test_xml_state_change_missing_transaction_uid_returns_400(self, client: TestClient, created_workitem_uid: str) -> None:
        """Contract: XML state change PUT with ProcedureStepState but no TransactionUID returns HTTP 400."""
        state_ds = Dataset()
        state_ds.ProcedureStepState = "IN PROGRESS"
        xml_body = dataset_to_xml(state_ds)

        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}/state",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400

    def test_xml_state_change_wrong_transaction_uid_on_claimed_workitem_returns_400(
        self, client: TestClient, in_progress_workitem_uid: tuple[str, str]
    ) -> None:
        """Contract: XML state change with wrong TransactionUID on a claimed workitem returns HTTP 400."""
        workitem_uid, _correct_transaction_uid = in_progress_workitem_uid
        state_ds = Dataset()
        state_ds.ProcedureStepState = "COMPLETED"
        state_ds.TransactionUID = str(generate_uid())
        xml_body = dataset_to_xml(state_ds)

        result = client.simulate_put(
            f"/workitems/{workitem_uid}/state",
            body=xml_body,
            headers={"Content-Type": "application/dicom+xml"},
        )
        assert result.status_code == 400
