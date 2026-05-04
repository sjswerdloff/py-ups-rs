"""Integration test for subscribing to UPS workitems."""

import json

import pytest
from falcon.testing.client import TestClient


@pytest.mark.integration
class TestSubscribe:
    """Test case for subscribing to UPS workitems."""

    def test_subscribe(self, client: TestClient, created_workitem_uid: str) -> None:
        """Test subscribing to a workitem."""
        ae_title = "SUBSCRIBE_TEST"
        payload = {
            "00741234": {"vr": "AE", "Value": [ae_title]},
            "0074120E": {"vr": "LT", "Value": ["ws://localhost:8080/subscribers/notifications"]},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")

        result = client.simulate_post(
            f"/workitems/{created_workitem_uid}/subscribers/{ae_title}",
            body=payload_bytes,
            headers={"Content-Type": "application/dicom+json"},
        )

        assert result.status_code in (200, 201)

    def test_unsubscribe(self, client: TestClient, created_workitem_uid: str, subscribed_subscriber_uid: str) -> None:
        """Test unsubscribing from a workitem."""
        result = client.simulate_delete(f"/workitems/{created_workitem_uid}/subscribers/{subscribed_subscriber_uid}")

        assert result.status_code == 200
