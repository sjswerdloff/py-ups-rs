"""Integration test for subscribing to UPS workitems."""

import pytest
from falcon.testing.client import TestClient


@pytest.mark.integration
class TestSubscribe:
    """Test case for subscribing to UPS workitems."""

    def test_subscribe(self, client: TestClient, created_workitem_uid: str) -> None:
        """Test subscribing to a workitem."""
        # Prepare test data
        subscriber_uid = "1.2.826.0.1.3680043.9.7133.2.1"
        payload = [
            {
                "00741000": {"vr": "UI", "Value": [created_workitem_uid]},
                "00741234": {"vr": "UI", "Value": [subscriber_uid]},
                "0074120E": {"vr": "LT", "Value": ["ws://localhost:8080/subscribers/notifications"]},
            }
        ]

        # Send request
        result = client.simulate_post(
            f"/workitems/{created_workitem_uid}/subscribers", json=payload, headers={"Content-Type": "application/dicom+json"}
        )

        # Verify response
        assert result.status_code == 201

        # Verify the subscription exists
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}/subscribers", headers={"Accept": "application/dicom+json"}
        )
        assert result.status_code == 200
        assert len(result.json) == 1
        assert result.json[0]["00741234"]["Value"][0] == subscriber_uid

    def test_unsubscribe(self, client: TestClient, created_workitem_uid: str, subscribed_subscriber_uid: str) -> None:
        """Test unsubscribing from a workitem."""
        # Send request
        result = client.simulate_delete(f"/workitems/{created_workitem_uid}/subscribers/{subscribed_subscriber_uid}")

        # Verify response
        assert result.status_code == 200

        # Verify the subscription is removed
        result = client.simulate_get(
            f"/workitems/{created_workitem_uid}/subscribers", headers={"Accept": "application/dicom+json"}
        )
        assert result.status_code == 200
        assert len(result.json) == 0
