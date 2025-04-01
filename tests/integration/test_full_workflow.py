"""Integration test for the complete UPS-RS workflow including WebSocket notifications."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import pytest
import websockets
from falcon.testing.client import TestClient


@pytest.mark.integration
class TestFullWorkflow:
    """Test case for the complete UPS-RS workflow."""

    async def connect_websocket(self, subscriber_uid: str) -> websockets.ClientConnection:
        """Connect to the WebSocket server."""
        uri = f"ws://localhost:8000/subscribers/{subscriber_uid}"
        async with websockets.connect(uri) as websocket:
            return websocket

    @asynccontextmanager
    async def notification_receiver(self, subscriber_uid: str) -> AsyncGenerator[list]:
        """Context manager for receiving notifications."""
        uri = f"ws://localhost:8000/subscribers/{subscriber_uid}"
        messages = []

        async def collect_messages() -> None:
            async with websockets.connect(uri) as websocket:
                while True:
                    try:
                        message = await websocket.recv()
                        messages.append(json.loads(message))
                    except websockets.exceptions.ConnectionClosed:
                        break

        # Start collecting messages in a separate task
        task = asyncio.create_task(collect_messages())

        try:
            yield messages
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_full_workflow(self, client: TestClient) -> None:
        """Test the complete workflow with notifications."""
        # 1. Subscribe to all workitems
        subscriber_uid = "1.2.826.0.1.3680043.9.7133.2.1"

        # Use a global subscription for all workitems
        subscription_payload = [
            {
                "00741234": {"vr": "UI", "Value": [subscriber_uid]},
                "0074120E": {"vr": "LT", "Value": ["ws://localhost:8000/subscribers/notifications"]},
                "00741200": {"vr": "CS", "Value": ["*"]},  # Subscribe to all workitems
            }
        ]

        result = client.simulate_post(
            "/workitems/1.2.840.10008.5.1.4.34.5/subscribers",
            json=subscription_payload,
            headers={"Content-Type": "application/dicom+json"},
        )
        assert result.status_code == 201

        # 2. Start listening for notifications
        async with self.notification_receiver(subscriber_uid) as messages:
            # Give the WebSocket connection time to establish
            await asyncio.sleep(0.5)

            # 3. Create a workitem
            workitem_uid = "1.2.826.0.1.3680043.9.7133.1.1"
            create_payload = [
                {
                    "00741000": {"vr": "UI", "Value": [workitem_uid]},
                    "00404005": {"vr": "DT", "Value": ["20220101120000"]},
                    "00404011": {"vr": "DT", "Value": ["20220101130000"]},
                    "00741200": {"vr": "CS", "Value": ["SCHEDULED"]},
                }
            ]

            result = client.simulate_post(
                "/workitems", json=create_payload, headers={"Content-Type": "application/dicom+json"}
            )
            assert result.status_code == 201

            # Wait for notification
            await asyncio.sleep(0.5)

            # Verify creation notification was received
            assert any(m["event_type"] == "creation" and m["workitem_uid"] == workitem_uid for m in messages)

            # 4. Change state to IN PROGRESS
            in_progress_payload = [
                {"00741000": {"vr": "UI", "Value": [workitem_uid]}, "00741200": {"vr": "CS", "Value": ["IN PROGRESS"]}}
            ]

            result = client.simulate_put(
                f"/workitems/{workitem_uid}/state",
                json=in_progress_payload,
                headers={"Content-Type": "application/dicom+json"},
            )
            assert result.status_code == 200

            # Wait for notification
            await asyncio.sleep(0.5)

            # Verify status change notification was received
            assert any(
                m["event_type"] == "status_change" and m["workitem_uid"] == workitem_uid and m["new_status"] == "IN PROGRESS"
                for m in messages
            )

            # 5. Update the workitem
            # TODO: The update should be an output information sequence
            # the current test update_payload is just wrong...
            update_payload = [
                {
                    "00741000": {"vr": "UI", "Value": [workitem_uid]},
                    "00404005": {"vr": "DT", "Value": ["20220102120000"]},
                    "00404011": {"vr": "DT", "Value": ["20220102130000"]},
                }
            ]

            result = client.simulate_put(
                f"/workitems/{workitem_uid}", json=update_payload, headers={"Content-Type": "application/dicom+json"}
            )
            assert result.status_code == 200

            # 6. Change state to COMPLETED
            completed_payload = [
                {"00741000": {"vr": "UI", "Value": [workitem_uid]}, "00741200": {"vr": "CS", "Value": ["COMPLETED"]}}
            ]

            result = client.simulate_put(
                f"/workitems/{workitem_uid}/state", json=completed_payload, headers={"Content-Type": "application/dicom+json"}
            )
            assert result.status_code == 200

            # Wait for notification
            await asyncio.sleep(0.5)

            # Verify status change notification was received
            assert any(
                m["event_type"] == "status_change" and m["workitem_uid"] == workitem_uid and m["new_status"] == "COMPLETED"
                for m in messages
            )

            # 7. Unsubscribe
            result = client.simulate_delete(f"/workitems/1.2.840.10008.5.1.4.34.5/subscribers/{subscriber_uid}")
            assert result.status_code == 200
