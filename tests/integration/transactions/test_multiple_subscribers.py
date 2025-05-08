"""Integration test for DICOMWeb UPS-RS Multiple Subscribers transaction."""

import asyncio
import json
import uuid
from copy import deepcopy
from typing import Any

import pytest
from falcon import Response
from falcon.testing import TestClient
from pydicom.uid import generate_uid

from pyupsrs.domain.models.ups import FILTERED_SUBSCRIPTION_UID


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
class TestMultipleSubscribers:
    """Test case for UPS-RS Multiple Subscribers transaction."""

    async def test_multiple_subscribers(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test that multiple subscribers receive appropriate notifications.

        This test:
        1. Creates two different subscriber AE Titles
        2. Creates different subscriptions for each (one global, one filtered)
        3. Establishes WebSocket connections for both subscribers
        4. Performs workitem operations
        5. Verifies each subscriber receives notifications based on their subscription parameters
        """
        # Create unique subscriber AE titles
        global_aetitle = f"GLOBAL_AE_{uuid.uuid4().hex[:6]}"[:16]
        filtered_aetitle = f"FILTER_AE_{uuid.uuid4().hex[:6]}"[:16]

        # Well-known UIDs
        global_uid = "1.2.840.10008.5.1.4.34.5"
        filtered_uid = FILTERED_SUBSCRIPTION_UID

        # Use ASGIConductor for WebSocket testing
        async with client as conductor:
            # Create global subscription for first subscriber (all states)
            global_payload = {
                "00741234": {"vr": "AE", "Value": [global_aetitle]},
                "00741000": {"vr": "CS", "Value": ["SCHEDULED", "IN PROGRESS", "COMPLETED", "CANCELED"]},
            }
            global_payload_bytes = json.dumps(global_payload).encode("utf-8")

            global_response = await conductor.simulate_post(
                f"/workitems/{global_uid}/subscribers/{global_aetitle}",
                body=global_payload_bytes,
                headers={"Content-Type": "application/dicom+json"},
            )
            assert global_response.status_code == 201

            # Create filtered subscription for second subscriber (only SCHEDULED state)
            # Note: Using URL query parameters for filter as per updated implementation
            filter_params = {
                "00741000": "SCHEDULED",  # Can only provide single value, not multi-valued
            }
            # Build filter parameter string
            filter_str = ",".join([f"{key}={value}" for key, value in filter_params.items()])
            filtered_endpoint = f"/workitems/{filtered_uid}/subscribers/{filtered_aetitle}?filter={filter_str}"

            filtered_response = await conductor.simulate_post(
                filtered_endpoint,
                headers={"Content-Type": "application/dicom+json"},
            )
            assert filtered_response.status_code == 201

            # Extract WebSocket URLs from responses
            assert "content-location" in global_response.headers
            global_location = global_response.headers["content-location"]
            global_subscriber_id = global_location.split("/")[-1]
            assert global_subscriber_id == global_aetitle

            assert "content-location" in filtered_response.headers
            filtered_location = filtered_response.headers["content-location"]
            filtered_subscriber_id = filtered_location.split("/")[-1]
            assert filtered_subscriber_id == filtered_aetitle

            # Connect to both WebSockets
            global_ws_path = f"/ws/subscribers/{global_subscriber_id}"
            filtered_ws_path = f"/ws/subscribers/{filtered_subscriber_id}"

            # We'll use a context manager to handle both WebSocket connections
            # First, establish the global subscription connection
            async with conductor.simulate_ws(global_ws_path) as global_ws:
                # Verify global connection is established
                await global_ws.wait_ready()
                assert global_ws.ready, "Global WebSocket connection not ready"

                # Now establish the filtered subscription connection
                async with conductor.simulate_ws(filtered_ws_path) as filtered_ws:
                    # Verify filtered connection is established
                    await filtered_ws.wait_ready()
                    assert filtered_ws.ready, "Filtered WebSocket connection not ready"

                    # Create a new workitem (initially in SCHEDULED state with a Scheduled Station)
                    new_workitem = deepcopy(sample_ups_workitem)
                    new_workitem["00080018"]["Value"] = [str(generate_uid())]

                    response = await conductor.simulate_post(
                        "/workitems",
                        body=json.dumps(new_workitem).encode("utf-8"),
                        headers={"Content-Type": "application/dicom+json"},
                    )
                    assert response.status_code == 201

                    workitem_uid = new_workitem["00080018"]["Value"][0]

                    # Both subscribers should receive a notification about the new workitem (SCHEDULED state)
                    try:
                        for i in range(2):
                            # Check global subscriber
                            global_msg = await asyncio.wait_for(global_ws.receive_json(), timeout=5.0)

                            # Verify the notification contains correct data
                            assert "00001000" in global_msg, "Missing Affected SOP Instance UID in global notification"
                            assert global_msg["00001000"]["Value"][0] == workitem_uid, (
                                "Incorrect workitem UID in global notification"
                            )
                            assert "00741000" in global_msg, "Missing Procedure Step State in global notification"
                            assert global_msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in global notification"
                            assert "00001002" in global_msg, "Missing Event Type ID"
                            event_type_id = global_msg["00001002"]["Value"][0]
                            if event_type_id == 1:  # UPS State Report
                                print(f"Global subscriber received UPS State Report for {workitem_uid} in iteration {i}")
                            elif event_type_id == 5:  # UPS Assigned
                                print(f"Global subscriber received UPS Assigned for {workitem_uid} in iteration {i}")
                            else:
                                raise AssertionError(f"Unexpected event type ID: {event_type_id}")

                        # Check filtered subscriber
                        for i in range(2):
                            filtered_msg = await asyncio.wait_for(filtered_ws.receive_json(), timeout=5.0)

                            # Verify the notification contains correct data
                            assert "00001000" in filtered_msg, "Missing Affected SOP Instance UID in filtered notification"
                            assert filtered_msg["00001000"]["Value"][0] == workitem_uid, (
                                "Incorrect workitem UID in filtered notification"
                            )
                            assert "00741000" in filtered_msg, "Missing Procedure Step State in filtered notification"
                            assert filtered_msg["00741000"]["Value"][0] == "SCHEDULED", (
                                "Incorrect state in filtered notification"
                            )
                            assert "00001002" in filtered_msg, "Missing Event Type ID"
                            event_type_id = filtered_msg["00001002"]["Value"][0]
                            if event_type_id == 1:  # UPS State Report
                                print(f"Filtered subscriber received UPS State Report for {workitem_uid} in iteration {i}")
                            elif event_type_id == 5:  # UPS Assigned
                                print(f"Filtered subscriber received UPS Assigned for {workitem_uid} in iteration {i}")
                            else:
                                raise AssertionError(f"Unexpected event type ID: {event_type_id}")

                    except TimeoutError as err:
                        raise AssertionError(
                            "One or both subscribers did not receive both notifications for new workitem"
                        ) from err

                    # Change workitem state to IN PROGRESS (only global subscriber should receive notification)
                    transaction_uid = str(generate_uid())
                    payload = {
                        "00081195": {"vr": "UI", "Value": [transaction_uid]},
                        "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
                    }
                    payload_bytes = json.dumps(payload).encode("utf-8")

                    response = await conductor.simulate_put(
                        f"/workitems/{workitem_uid}/state",
                        body=payload_bytes,
                        headers={"Content-Type": "application/dicom+json"},
                    )
                    assert response.status_code == 200

                    # Global subscriber should receive notification
                    try:
                        global_msg = await asyncio.wait_for(global_ws.receive_json(), timeout=5.0)

                        # Verify the notification contains correct data
                        assert "00741000" in global_msg, "Missing Procedure Step State in global notification"
                        assert global_msg["00741000"]["Value"][0] == "IN PROGRESS", "Incorrect state in global notification"
                    except TimeoutError as err:
                        raise AssertionError("Global subscriber did not receive notification for IN PROGRESS state") from err

                    # Filtered subscriber should NOT receive notification for IN PROGRESS
                    try:
                        # Set a shorter timeout for the test
                        await asyncio.wait_for(filtered_ws.receive_json(), timeout=2.0)
                        raise AssertionError(
                            "Filtered subscriber received notification for IN PROGRESS state although it was not in the filter"
                        )
                    except TimeoutError:
                        # This is the expected behavior - no message should be received
                        pass

                    # Change workitem state to COMPLETED (only global subscriber should receive notification)
                    # since our filtered subscriber is only for SCHEDULED state
                    payload = {
                        "00081195": {"vr": "UI", "Value": [transaction_uid]},
                        "00741000": {"vr": "CS", "Value": ["COMPLETED"]},
                    }
                    payload_bytes = json.dumps(payload).encode("utf-8")

                    response = await conductor.simulate_put(
                        f"/workitems/{workitem_uid}/state",
                        body=payload_bytes,
                        headers={"Content-Type": "application/dicom+json"},
                    )
                    assert response.status_code == 200

                    # Only Global subscriber should receive notification for COMPLETED state
                    try:
                        # Check global subscriber
                        global_msg = await asyncio.wait_for(global_ws.receive_json(), timeout=5.0)

                        # Verify the notification contains correct data
                        assert "00741000" in global_msg, "Missing Procedure Step State in global notification"
                        assert global_msg["00741000"]["Value"][0] == "COMPLETED", "Incorrect state in global notification"
                    except TimeoutError as err:
                        raise AssertionError("Global subscriber did not receive notification for COMPLETED state") from err

                    # Filtered subscriber should NOT receive notification for COMPLETED state
                    #  (since filter is only for SCHEDULED)
                    try:
                        # Set a shorter timeout for the test
                        await asyncio.wait_for(filtered_ws.receive_json(), timeout=2.0)
                        raise AssertionError(
                            "Filtered subscriber received notification for COMPLETED state although it was not in the filter"
                        )
                    except TimeoutError:
                        # This is the expected behavior - no message should be received
                        pass
