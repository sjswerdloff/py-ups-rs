"""Integration test for DICOMWeb UPS-RS Global Subscribe transaction."""

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


def suspend_subscription_helper(client: TestClient, aetitle: str, dicom_headers: dict[str, str]) -> Response:
    """
    Suspend a global subscription.

    Args:
        client: Falcon TestClient
        aetitle: AE Title of the subscriber
        dicom_headers: DICOM HTTP headers

    Returns:
        Falcon Response object

    """
    return client.simulate_post(f"/workitems/1.2.840.10008.5.1.4.34.5/subscribers/{aetitle}/suspend", headers=dicom_headers)


@pytest.mark.asyncio(loop_scope="function")
class TestGlobalSubscription:
    """Test case for UPS-RS Global Subscribe transaction."""

    async def test_global_subscription_notifications(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test subscribing to all workitems (global subscription) and receiving notifications.

        This test:
        1. Creates a global subscription
        2. Establishes a WebSocket connection using the URL from the subscription response
        3. Creates a new workitem and verifies a notification is received
        4. Changes the workitem state and verifies notifications are received
        5. Tests suspending the subscription
        """
        # Create a unique subscriber AE title
        aetitle = f"GLOBAL_AE_{uuid.uuid4().hex[:6]}"  # AE Titles are limited to 16 characters

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
                    for i in range(2):
                        # Set a reasonable timeout for the test
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                        # Verify the notification contains correct data
                        assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                        assert msg["00001000"]["Value"][0] == workitem_uid, "Incorrect workitem UID in notification"
                        assert "00741000" in msg, "Missing Procedure Step State in notification"
                        assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                        event_type_id = msg["00001002"]["Value"][0]
                        if event_type_id == 1:  # UPS State Report
                            print(f"Global subscriber received UPS State Report for {workitem_uid} in iteration {i}")
                        elif event_type_id == 5:  # UPS Assigned
                            print(f"Global subscriber received UPS Assigned for {workitem_uid} in iteration {i}")
                        else:  # Unexpected event type
                            raise AssertionError(f"Unexpected event type ID: {event_type_id}")
                except TimeoutError as err:
                    raise AssertionError("No notification received for new workitem") from err

                # Change workitem state to trigger more notifications
                transaction_uid = str(generate_uid())
                payload = {
                    "00081195": {"vr": "UI", "Value": [transaction_uid]},
                    "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
                }
                payload_bytes = json.dumps(payload).encode("utf-8")

                response = await conductor.simulate_put(
                    f"/workitems/{workitem_uid}/state", body=payload_bytes, headers={"Content-Type": "application/dicom+json"}
                )
                assert response.status_code == 200

                # Wait for the state change notification
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                    # Verify the notification contains correct state
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "IN PROGRESS", "Incorrect state in notification"
                except TimeoutError as err:
                    raise AssertionError("No notification received for state change to IN PROGRESS") from err

                # Suspend the subscription
                response = await conductor.simulate_post(
                    f"/workitems/1.2.840.10008.5.1.4.34.5/subscribers/{aetitle}/suspend", headers=dicom_headers
                )
                assert response.status_code == 200

                # Change state again - should not receive notification after subscription suspension
                # use previous transaction uid, do not create a new one transaction_uid = str(generate_uid())
                payload = {
                    "00081195": {"vr": "UI", "Value": [transaction_uid]},
                    "00741000": {"vr": "CS", "Value": ["COMPLETED"]},
                }
                payload_bytes = json.dumps(payload).encode("utf-8")

                response = await conductor.simulate_put(
                    f"/workitems/{workitem_uid}/state", body=payload_bytes, headers={"Content-Type": "application/dicom+json"}
                )
                assert response.status_code == 200

                # Try to receive a message, but should timeout
                try:
                    # Set a shorter timeout for the test
                    await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    raise AssertionError("Received notification after subscription was suspended")
                except TimeoutError:
                    # This is the expected behavior - no message should be received
                    pass
