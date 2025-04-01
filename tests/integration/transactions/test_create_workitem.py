"""Integration test for creating a UPS workitem."""

import pytest
from falcon.testing.client import TestClient


@pytest.mark.integration
class TestCreateWorkItem:
    """Test case for creating a UPS workitem."""

    def test_create_workitem(self, client: TestClient) -> None:
        """Test creating a workitem."""
        # Prepare test data
        payload = [
            {
                "00741000": {"vr": "UI", "Value": ["1.2.826.0.1.3680043.9.7133.1.1"]},
                "00404005": {"vr": "DT", "Value": ["20220101120000"]},
                "00404011": {"vr": "DT", "Value": ["20220101130000"]},
                "00741200": {"vr": "CS", "Value": ["SCHEDULED"]},
            }
        ]

        # Send request
        result = client.simulate_post("/workitems", json=payload, headers={"Content-Type": "application/dicom+json"})

        # Verify response
        assert result.status_code == 201
        assert "Location" in result.headers

        # Verify the workitem exists
        location = result.headers["Location"]
        result = client.simulate_get(location, headers={"Accept": "application/dicom+json"})
        assert result.status_code == 200
        assert result.json[0]["00741000"]["Value"][0] == "1.2.826.0.1.3680043.9.7133.1.1"
        assert result.json[0]["00741200"]["Value"][0] == "SCHEDULED"
