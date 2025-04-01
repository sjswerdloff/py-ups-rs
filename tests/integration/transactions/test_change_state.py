"""Integration test for changing UPS workitem state."""

import pytest
from falcon.testing.client import TestClient


@pytest.mark.integration
class TestChangeState:
    """Test case for changing UPS workitem state."""

    def test_change_to_in_progress(self, client: TestClient, created_workitem_uid: str) -> None:
        """Test changing a workitem state to IN PROGRESS."""
        # Prepare test data
        payload = [
            {"00741000": {"vr": "UI", "Value": [created_workitem_uid]}, "00741200": {"vr": "CS", "Value": ["IN PROGRESS"]}}
        ]

        # Send request
        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}/state", json=payload, headers={"Content-Type": "application/dicom+json"}
        )

        # Verify response
        assert result.status_code == 200

        # Verify the state was changed
        result = client.simulate_get(f"/workitems/{created_workitem_uid}", headers={"Accept": "application/dicom+json"})
        assert result.status_code == 200
        assert result.json[0]["00741200"]["Value"][0] == "IN PROGRESS"

    def test_change_to_completed(self, client: TestClient, in_progress_workitem_uid: str) -> None:
        """Test changing a workitem state to COMPLETED."""
        # Prepare test data
        payload = [
            {"00741000": {"vr": "UI", "Value": [in_progress_workitem_uid]}, "00741200": {"vr": "CS", "Value": ["COMPLETED"]}}
        ]

        # Send request
        result = client.simulate_put(
            f"/workitems/{in_progress_workitem_uid}/state", json=payload, headers={"Content-Type": "application/dicom+json"}
        )

        # Verify response
        assert result.status_code == 200

        # Verify the state was changed
        result = client.simulate_get(f"/workitems/{in_progress_workitem_uid}", headers={"Accept": "application/dicom+json"})
        assert result.status_code == 200
        assert result.json[0]["00741200"]["Value"][0] == "COMPLETED"
