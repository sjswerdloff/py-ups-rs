"""Integration test for updating a UPS workitem."""

import pytest
from falcon.testing.client import TestClient


@pytest.mark.integration
class TestUpdateWorkItem:
    """Test case for updating a UPS workitem."""

    def test_update_workitem(self, client: TestClient, created_workitem_uid: str) -> None:
        """Test updating a workitem."""
        # Prepare test data
        payload = [
            {
                "00741000": {"vr": "UI", "Value": [created_workitem_uid]},
                "00404005": {"vr": "DT", "Value": ["20220102120000"]},
                "00404011": {"vr": "DT", "Value": ["20220102130000"]},
            }
        ]

        # Send request
        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}", json=payload, headers={"Content-Type": "application/dicom+json"}
        )

        # Verify response
        assert result.status_code == 200

        # Verify the workitem was updated
        result = client.simulate_get(f"/workitems/{created_workitem_uid}", headers={"Accept": "application/dicom+json"})
        assert result.status_code == 200
        assert result.json[0]["00404005"]["Value"][0] == "20220102120000"
        assert result.json[0]["00404011"]["Value"][0] == "20220102130000"
