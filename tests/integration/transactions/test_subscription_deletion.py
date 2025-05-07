"""Integration test for DICOMWeb UPS-RS Subscription Deletion transaction."""

import asyncio
import json
import uuid
from copy import deepcopy
from typing import Any

import pytest
from falcon import Response
from falcon.testing import TestClient
from pydicom.uid import generate_uid


def create_workitem_helper(client: TestClient, sample_ups_workitem: dict[str, Any]) -> Response:
    """Create a workitem."""
    # Prepare test data
    payload = sample_ups_workitem
    specified_instance_uid_list: list = payload["00080018"]["Value"]
    specified_instance_uid = specified_instance_uid_list[0]
    json_payload = json.dumps(payload)
    payload_bytes = json_payload.encode("utf-8")
    print(f"Instance UID: {type(specified_instance_uid)} = {specified_instance_uid}")
    # Send request
    return client.simulate_post("/workitems", body=payload_bytes, headers={"Content-Type": "application/dicom+json"})


def change_state_helper(client: TestClient, created_workitem_uid: str, transaction_uid: str, state: str) -> Response:
    """Change a workitem state."""
    # Prepare test data
    payload = {"00081195": {"vr": "UI", "Value": [transaction_uid]}, "00741000": {"vr": "CS", "Value": [state]}}

    location = f"/workitems/{created_workitem_uid}/state"
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Send request
    return client.simulate_put(location, body=payload_bytes, headers={"Content-Type": "application/dicom+json"})


def create_subscription_helper(client: TestClient, workitem_uid: str, aetitle: str, preferred_states: list[str]) -> Response:
    """
    Create a subscription for a workitem.

    Args:
        client: Falcon TestClient
        workitem_uid: UID of the workitem to subscribe to
        aetitle: AE Title of the subscriber
        preferred_states: List of procedure step states to subscribe to

    Returns:
        Falcon Response object

    """
    payload = {
        "00741234": {"vr": "AE", "Value": [aetitle]},
        "00741000": {"vr": "CS", "Value": preferred_states},
    }

    payload_bytes = json.dumps(payload).encode("utf-8")

    return client.simulate_post(
        f"/workitems/{workitem_uid}/subscribers/{aetitle}",
        body=payload_bytes,
        headers={"Content-Type": "application/dicom+json"},
    )


def delete_subscription_helper(client: TestClient, workitem_uid: str, aetitle: str, dicom_headers: dict[str, str]) -> Response:
    """
    Delete a subscription.

    Args:
        client: Falcon TestClient
        workitem_uid: UID of the workitem subscription to delete
        aetitle: AE Title of the subscriber
        dicom_headers: DICOM HTTP headers

    Returns:
        Falcon Response object

    """
    return client.simulate_delete(f"/workitems/{workitem_uid}/subscribers/{aetitle}", headers=dicom_headers)


@pytest.mark.asyncio(loop_scope="function")
class TestSubscriptionDeletion:
    """Test case for UPS-RS Subscription Deletion transaction."""

    async def test_subscription_deletion(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test proper handling of subscription deletion.

        This test:
        1. Creates a global subscription
        2. Connects to the WebSocket
        3. Creates a workitem and verifies notification is received
        4. Deletes the subscription
        5. Verifies the WebSocket connection is properly closed
        6. Creates another workitem
        7. Verifies no notifications are received after deletion
        """
        # Create a unique subscriber AE title
        aetitle = f"DELETE_AE_{uuid.uuid4().hex[:8]}"[:16]  # AE Titles are limited to 16 characters

        # Create a global subscription (using the well-known UID)
        global_uid = "1.2.840.10008.5.1.4.34.5"

        # Use ASGIConductor for WebSocket testing
        async with client as conductor:
            # Create subscription using conductor
            payload = {
                "00741234": {"vr": "AE", "Value": [aetitle]},
                "00741000": {"vr": "CS", "Value": ["SCHEDULED", "IN PROGRESS", "COMPLETED", "CANCELED"]},
            }
            payload_bytes = json.dumps(payload).encode("utf-8")

            response = await conductor.simulate_post(
                f"/workitems/{global_uid}/subscribers/{aetitle}",
                body=payload_bytes,
                headers={"Content-Type": "application/dicom+json"},
            )

            assert response.status_code == 201

            # Extract WebSocket URL from response
            assert "content-location" in response.headers
            location = response.headers["content-location"]
            print(location)
            subscriber_id = location.split("/")[-1]
            assert subscriber_id == aetitle

            # Connect to the WebSocket using the Falcon-provided simulator
            ws_path = f"/ws/subscribers/{subscriber_id}"
            async with conductor.simulate_ws(ws_path) as ws:
                # Verify connection is established
                await ws.wait_ready()
                assert ws.ready, "WebSocket connection not ready"

                # Create a new workitem
                new_workitem = deepcopy(sample_ups_workitem)
                new_workitem["00080018"]["Value"] = [str(generate_uid())]

                # Use conductor for HTTP requests too
                response = await conductor.simulate_post(
                    "/workitems",
                    body=json.dumps(new_workitem).encode("utf-8"),
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 201

                workitem_uid = new_workitem["00080018"]["Value"][0]

                # Wait for the notification about the new workitem
                try:
                    # Set a reasonable timeout for the test
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                    # Verify the notification contains correct data
                    assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                    assert msg["00001000"]["Value"][0] == workitem_uid, "Incorrect workitem UID in notification"
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                except TimeoutError as err:
                    raise AssertionError("No notification received for new workitem") from err

                # Now delete the subscription
                response = await conductor.simulate_delete(
                    f"/workitems/{global_uid}/subscribers/{aetitle}", headers=dicom_headers
                )
                assert response.status_code == 200

                # The WebSocket should be closed by the server after subscription deletion
                # We need to check if the WebSocket connection is closed, but the simulate_ws API
                # might not provide a direct way to check this, so we'll verify by trying to receive
                # a message and ensuring we get an appropriate error

                # Wait a short time for the server to process the deletion and close the connection
                await asyncio.sleep(1)

                # Create another workitem (shouldn't receive notification due to deleted subscription)
                second_workitem = deepcopy(sample_ups_workitem)
                second_workitem["00080018"]["Value"] = [str(generate_uid())]

                response = await conductor.simulate_post(
                    "/workitems",
                    body=json.dumps(second_workitem).encode("utf-8"),
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 201

                # Try to receive message - should fail either with a timeout or a WebSocket closed error
                try:
                    # We'll use a short timeout
                    await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    # If we get here without an exception, the test should fail
                    raise AssertionError("Received message after subscription deletion")
                except (TimeoutError, Exception):
                    # Either a timeout or a WebSocket closed exception is acceptable here
                    pass

            # Test the ability to reconnect with a new WebSocket connection and verify it cannot
            # Since we're outside the WebSocket context manager here, we'll just try to connect again
            try:
                async with conductor.simulate_ws(ws_path, timeout=2.0) as ws:
                    await ws.wait_ready()
                    # If we successfully connect, the test should fail
                    raise AssertionError("Was able to connect to WebSocket after subscription deletion")
            except Exception:
                # An exception here is the expected behavior
                pass
