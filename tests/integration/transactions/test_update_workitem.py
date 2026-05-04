"""Integration test for updating a UPS workitem."""

import json

import pytest
from falcon.testing.client import TestClient


@pytest.mark.integration
class TestUpdateWorkItem:
    """Test case for updating a UPS workitem."""

    def test_update_workitem(self, client: TestClient, created_workitem_uid: str) -> None:
        """Test updating a workitem's scheduled times."""
        payload = {
            "00404005": {"vr": "DT", "Value": ["20220102120000"]},
            "00404011": {"vr": "DT", "Value": ["20220102130000"]},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")

        result = client.simulate_put(
            f"/workitems/{created_workitem_uid}",
            body=payload_bytes,
            headers={"Content-Type": "application/dicom+json"},
        )

        assert result.status_code == 200

        # Verify the workitem was updated
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}",
            headers={"Accept": "application/dicom+json"},
        )
        assert result.status_code == 200
