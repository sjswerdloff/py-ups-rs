"""Integration test for changing UPS workitem state."""

import json

import pytest
from falcon.testing.client import TestClient
from pydicom.uid import generate_uid


@pytest.mark.integration
class TestChangeState:
    """Test case for changing UPS workitem state."""

    def test_change_to_in_progress(self, client: TestClient, created_workitem_uid: str) -> None:
        """Test changing a workitem state to IN PROGRESS."""
        transaction_uid = str(generate_uid())
        payload = {
            "00081195": {"vr": "UI", "Value": [transaction_uid]},
            "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")

        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}/state",
            body=payload_bytes,
            headers={"Content-Type": "application/dicom+json"},
        )

        assert result.status_code == 200

    def test_change_to_completed(self, client: TestClient, in_progress_workitem_uid: tuple[str, str]) -> None:
        """Test changing a workitem state from IN PROGRESS to COMPLETED."""
        workitem_uid, transaction_uid = in_progress_workitem_uid
        payload = {
            "00081195": {"vr": "UI", "Value": [transaction_uid]},
            "00741000": {"vr": "CS", "Value": ["COMPLETED"]},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")

        result = client.simulate_put(
            f"/workitems/{workitem_uid}/state",
            body=payload_bytes,
            headers={"Content-Type": "application/dicom+json"},
        )

        assert result.status_code == 200
