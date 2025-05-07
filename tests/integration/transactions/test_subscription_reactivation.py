"""Integration test for DICOMWeb UPS-RS Subscription Reactivation transaction."""

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


def suspend_subscription_helper(
    client: TestClient, workitem_uid: str, aetitle: str, dicom_headers: dict[str, str]
) -> Response:
    """
    Suspend a subscription.

    Args:
        client: Falcon TestClient
        workitem_uid: UID of the workitem subscription to suspend
        aetitle: AE Title of the subscriber
        dicom_headers: DICOM HTTP headers

    Returns:
        Falcon Response object

    """
    return client.simulate_post(f"/workitems/{workitem_uid}/subscribers/{aetitle}/suspend", headers=dicom_headers)


@pytest.mark.asyncio(loop_scope="function")
class TestSubscriptionReactivation:
    """Test case for UPS-RS Subscription Reactivation After Suspension."""

    async def test_subscription_reactivation(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test the ability to reactivate a previously suspended subscription.

        This test:
        1. Creates a global subscription
        2. Establishes a WebSocket connection
        3. Creates a workitem and verifies notification is received
        4. Suspends the subscription
        5. Creates another workitem and verifies NO notification is received
        6. Reactivates the subscription
        7. Creates a third workitem and verifies notification is received again
        """
        # Create a unique subscriber AE title
        aetitle = f"REACT_AE_{uuid.uuid4().hex[:6]}"  # AE Titles are limited to 16 characters

        # Global subscription well-known UID
        global_uid = "1.2.840.10008.5.1.4.34.5"

        # Use ASGIConductor for WebSocket testing
        async with client as conductor:
            # Create global subscription
            response = await conductor.simulate_post(
                f"/workitems/{global_uid}/subscribers/{aetitle}",
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

                # Create a first workitem - should trigger notification
                first_workitem = deepcopy(sample_ups_workitem)
                first_workitem["00080018"]["Value"] = [str(generate_uid())]

                response = await conductor.simulate_post(
                    "/workitems",
                    body=json.dumps(first_workitem).encode("utf-8"),
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 201

                first_workitem_uid = first_workitem["00080018"]["Value"][0]

                # Wait for the notification about the first workitem
                try:
                    # Set a reasonable timeout for the test
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                    # Verify the notification contains correct data
                    assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                    assert msg["00001000"]["Value"][0] == first_workitem_uid, "Incorrect workitem UID in notification"
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                except TimeoutError as err:
                    raise AssertionError("No notification received for first workitem") from err

                # Suspend the subscription
                response = await conductor.simulate_post(
                    f"/workitems/{global_uid}/subscribers/{aetitle}/suspend", headers=dicom_headers
                )
                assert response.status_code == 200

                # Create a second workitem - should NOT trigger notification due to suspended subscription
                second_workitem = deepcopy(sample_ups_workitem)
                second_workitem["00080018"]["Value"] = [str(generate_uid())]

                response = await conductor.simulate_post(
                    "/workitems",
                    body=json.dumps(second_workitem).encode("utf-8"),
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 201

                # Try to receive a notification for the second workitem - should timeout
                try:
                    # Set a shorter timeout for the test
                    await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    raise AssertionError("Received notification while subscription was suspended")
                except TimeoutError:
                    # This is the expected behavior - no message should be received
                    pass

                # Reactivate the subscription by creating it again with the same parameters
                response = await conductor.simulate_post(
                    f"/workitems/{global_uid}/subscribers/{aetitle}",
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 201

                # Create a third workitem - should trigger notification again after reactivation
                third_workitem = deepcopy(sample_ups_workitem)
                third_workitem["00080018"]["Value"] = [str(generate_uid())]

                response = await conductor.simulate_post(
                    "/workitems",
                    body=json.dumps(third_workitem).encode("utf-8"),
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 201

                third_workitem_uid = third_workitem["00080018"]["Value"][0]

                # Wait for the notification about the third workitem
                try:
                    # Set a reasonable timeout for the test
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                    # Verify the notification contains correct data
                    assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                    assert msg["00001000"]["Value"][0] == third_workitem_uid, "Incorrect workitem UID in notification"
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                except TimeoutError as err:
                    raise AssertionError("No notification received for third workitem after reactivation") from err
