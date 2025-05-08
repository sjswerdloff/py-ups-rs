"""Integration test for DICOMWeb UPS-RS Batch Notification Processing."""

import asyncio
import json
import time
import uuid
from copy import deepcopy
from typing import Any

import pytest
from falcon import Response
from falcon.testing import ASGIConductor, TestClient
from pydicom.uid import generate_uid


async def create_custom_workitem(
    conductor: ASGIConductor, base_workitem: dict[str, Any], priority: str = "MEDIUM", state: str = "SCHEDULED"
) -> Response:
    """
    Create a workitem with custom priority and state.

    Args:
        conductor: async Falcon TestClient as ASGIConductor
        base_workitem: Base workitem template to modify
        priority: Priority to set (LOW, MEDIUM, HIGH)
        state: Initial state (typically SCHEDULED)

    Returns:
        Response

    """
    # Create a deep copy to avoid modifying the original
    custom_workitem = deepcopy(base_workitem)

    # Set a unique instance UID
    custom_workitem["00080018"]["Value"] = [str(generate_uid())]

    # Set the priority
    custom_workitem["00741200"] = {"vr": "CS", "Value": [priority]}

    # Set the state (typically SCHEDULED for new workitems)
    custom_workitem["00741000"] = {"vr": "CS", "Value": [state]}

    # Convert to JSON and send
    payload_bytes = json.dumps(custom_workitem).encode("utf-8")

    response = await conductor.simulate_post(
        "/workitems", body=payload_bytes, headers={"Content-Type": "application/dicom+json"}
    )

    return response


async def change_state_async(conductor: ASGIConductor, workitem_uid: str, transaction_uid: str, state: str) -> Response:
    """
    Change a workitem state asynchronously.

    Args:
        conductor: async Falcon TestClient as ASGIConductor
        workitem_uid: UID of the workitem to change
        transaction_uid: Transaction UID for the change
        state: New state to set

    Returns:
        Response

    """
    # Prepare test data
    payload = {"00081195": {"vr": "UI", "Value": [transaction_uid]}, "00741000": {"vr": "CS", "Value": [state]}}

    location = f"/workitems/{workitem_uid}/state"
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Send request
    return await conductor.simulate_put(location, body=payload_bytes, headers={"Content-Type": "application/dicom+json"})


@pytest.mark.asyncio(loop_scope="function")
class TestBatchNotificationProcessing:
    """Test case for UPS-RS Batch Notification Processing."""

    async def test_batch_notification_processing(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test the system's ability to handle multiple notifications in quick succession.

        This test:
        1. Creates a subscription
        2. Establishes WebSocket connection
        3. Rapidly creates multiple workitems in sequence
        4. Verifies all expected notifications are received in the correct order
        5. Rapidly changes states of multiple workitems
        6. Verifies all state change notifications are received
        """
        # Create a unique subscriber AE title
        aetitle = f"BATCH_AE_{uuid.uuid4().hex[:6]}"[:16]  # AE Titles are limited to 16 characters

        # Global subscription well-known UID
        global_uid = "1.2.840.10008.5.1.4.34.5"

        # Number of workitems to create in batch
        num_workitems = 5

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
                time.sleep(2)
                # Step 1: Rapidly create multiple workitems
                workitem_uids = []
                for i in range(num_workitems):
                    response = await create_custom_workitem(
                        conductor,
                        sample_ups_workitem,
                        priority=["LOW", "MEDIUM", "HIGH"][i % 3],  # Cycle through priorities
                        state="SCHEDULED",
                    )
                    assert response.status_code == 201
                    workitem_uid = response.json["00080018"]["Value"][0]
                    workitem_uids.append(workitem_uid)
                    print(f"Created workitem {i + 1} with UID: {workitem_uid}")

                scheduled_workitems = num_workitems
                assigned_workitems = num_workitems
                received_assigned_workitems = 0
                received_scheduled_workitems = 0

                # Step 2: Verify all notifications are received (in the correct order?)
                received_uids = []
                i = 0
                for i in range(scheduled_workitems + assigned_workitems):
                    try:
                        # Set a reasonable timeout for the test
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                        # Verify the notification contains correct data
                        assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                        uid = msg["00001000"]["Value"][0]

                        assert "00001002" in msg, "Missing Event Type ID"
                        event_type_id = msg["00001002"]["Value"][0]
                        if event_type_id == 1:  # UPS State Report
                            received_scheduled_workitems += 1
                        elif event_type_id == 5:  # UPS Assigned
                            received_assigned_workitems += 1
                            received_uids.append(uid)  # only track assigned workitems (ignore state changes)
                        else:
                            raise AssertionError(f"Unexpected event type ID: {event_type_id}")

                        assert "00741000" in msg, "Missing Procedure Step State in notification"
                        assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                    except TimeoutError as err:
                        raise AssertionError(
                            f"Did not receive notification {i + 1} out of "
                            f"{scheduled_workitems + assigned_workitems}, expecting 2 per workitem"
                        ) from err

                count_received_uids = len(received_uids)
                count_no_dupes = len(set(received_uids))
                # Verify all workitems were notified
                # Note: Order might not be guaranteed due to concurrent processing
                assert set(received_uids) == set(workitem_uids), (
                    f"Not all workitem notifications were received:"
                    f"{len(set(received_uids))} out of {len(set(workitem_uids))}"
                    f"Duplicate UIDs received: {count_received_uids - count_no_dupes}"
                    f"Missing: {set(workitem_uids) - set(received_uids)}"
                    f"Extra: {set(received_uids) - set(workitem_uids)}"
                )

                # Clear out any remaining messages
                print("Clearing out any remaining messages")
                remaining_count = 0
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                        remaining_count += 1
                        print(f"Remaining message {remaining_count} with content: {msg}")
                except TimeoutError:
                    pass

                # Step 3: Prepare for batch state changes
                # We'll change each workitem's state to IN PROGRESS
                transaction_uid = str(generate_uid())  # Single transaction UID for all changes

                # Step 4: Rapidly change states of multiple workitems
                for i, workitem_uid in enumerate(workitem_uids):
                    response = await change_state_async(conductor, workitem_uid, transaction_uid, "IN PROGRESS")
                    assert response.status_code == 200
                    print(f"Changed workitem {i + 1} state to IN PROGRESS")

                # Step 5: Verify all state change notifications are received
                received_state_change_uids = []
                for i in range(num_workitems):
                    try:
                        # Set a reasonable timeout for the test
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                        # Verify the notification contains correct state change data
                        uid = msg["00001000"]["Value"][0] if "00001000" in msg else None
                        received_state_change_uids.append(uid)
                        assert "00741000" in msg, "Missing Procedure Step State in notification"
                        assert msg["00741000"]["Value"][0] == "IN PROGRESS", "Incorrect state in notification"
                    except TimeoutError as err:
                        raise AssertionError(
                            f"Did not receive state change notification {i + 1} out of {num_workitems}"
                        ) from err

                # Verify all state changes were notified
                # Note: Order might not be guaranteed due to concurrent processing
                assert set(received_state_change_uids) == set(workitem_uids), (
                    "Not all state change notifications were received"
                )
