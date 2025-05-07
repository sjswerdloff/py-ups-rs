"""Integration test for DICOMWeb UPS-RS Specific Workitem Subscription transaction."""

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


@pytest.mark.asyncio(loop_scope="function")
class TestSpecificWorkitemSubscription:
    """Test case for UPS-RS Subscription to a Specific Workitem."""

    async def test_specific_workitem_subscription(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test subscribing to a specific workitem and receiving notifications only for that workitem.

        This test:
        1. Creates a workitem
        2. Creates a subscription specifically for this workitem's UID
        3. Establishes a WebSocket connection using the URL from the subscription response
        4. Creates another workitem and verifies NO notification is received
        5. Changes the state of the first workitem and verifies notification is received
        """
        # Create a unique subscriber AE title
        aetitle = f"SPECIFIC_AE_{uuid.uuid4().hex[:6]}"  # AE Titles are limited to 16 characters

        # Use ASGIConductor for WebSocket testing
        async with client as conductor:
            # First, create a specific workitem to subscribe to
            first_workitem = deepcopy(sample_ups_workitem)
            first_workitem["00080018"]["Value"] = [str(generate_uid())]

            response = await conductor.simulate_post(
                "/workitems",
                body=json.dumps(first_workitem).encode("utf-8"),
                headers={"Content-Type": "application/dicom+json"},
            )
            assert response.status_code == 201

            first_workitem_uid = first_workitem["00080018"]["Value"][0]
            print(f"Created first workitem with UID: {first_workitem_uid}")

            # Create subscription specifically for the first workitem
            payload = {
                "00741234": {"vr": "AE", "Value": [aetitle]},
                "00741000": {"vr": "CS", "Value": ["SCHEDULED", "IN PROGRESS", "COMPLETED", "CANCELED"]},
            }
            payload_bytes = json.dumps(payload).encode("utf-8")

            response = await conductor.simulate_post(
                f"/workitems/{first_workitem_uid}/subscribers/{aetitle}",
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

                # Create a SECOND workitem - should NOT trigger notification since we're only subscribed to the first
                second_workitem = deepcopy(sample_ups_workitem)
                second_workitem["00080018"]["Value"] = [str(generate_uid())]

                response = await conductor.simulate_post(
                    "/workitems",
                    body=json.dumps(second_workitem).encode("utf-8"),
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 201

                second_workitem_uid = second_workitem["00080018"]["Value"][0]
                print(f"Created second workitem with UID: {second_workitem_uid}")

                # Try to receive a notification for the second workitem - should timeout
                try:
                    # Set a shorter timeout for the test since we expect no message
                    await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    raise AssertionError("Received notification for second workitem although not subscribed to it")
                except TimeoutError:
                    # This is the expected behavior - no message should be received for the second workitem
                    pass

                # Change state of the FIRST workitem - should trigger notification
                transaction_uid = str(generate_uid())
                payload = {
                    "00081195": {"vr": "UI", "Value": [transaction_uid]},
                    "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
                }
                payload_bytes = json.dumps(payload).encode("utf-8")

                response = await conductor.simulate_put(
                    f"/workitems/{first_workitem_uid}/state",
                    body=payload_bytes,
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 200

                # Wait for the notification about the first workitem's state change
                try:
                    # Set a reasonable timeout for the test
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                    # Verify the notification contains correct data
                    assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                    assert msg["00001000"]["Value"][0] == first_workitem_uid, "Incorrect workitem UID in notification"
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "IN PROGRESS", "Incorrect state in notification"
                except TimeoutError as err:
                    raise AssertionError("No notification received for first workitem state change") from err

                # Now change state of the SECOND workitem - should NOT trigger notification
                second_transaction_uid = str(generate_uid())
                payload = {
                    "00081195": {"vr": "UI", "Value": [second_transaction_uid]},
                    "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
                }
                payload_bytes = json.dumps(payload).encode("utf-8")

                response = await conductor.simulate_put(
                    f"/workitems/{second_workitem_uid}/state",
                    body=payload_bytes,
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 200

                # Try to receive a notification for the second workitem's state change - should timeout
                try:
                    # Set a shorter timeout for the test
                    await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    raise AssertionError(
                        "Received notification for second workitem state change although not subscribed to it"
                    )
                except TimeoutError:
                    # This is the expected behavior - no message should be received for the second workitem
                    pass
