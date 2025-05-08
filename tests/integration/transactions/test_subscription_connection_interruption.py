"""Integration test for DICOMWeb UPS-RS handling connection interruptions."""

import asyncio
import json
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


@pytest.mark.asyncio(loop_scope="function")
class TestSubscriptionConnectionInterruption:
    """Test case for UPS-RS handling connection interruptions."""

    async def test_connection_interruption(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test resilience to connection issues.

        This test:
        1. Creates a subscription
        2. Establishes WebSocket connection
        3. Creates a workitem and verifies notification is received
        4. Simulates a connection drop (close and reopen)
        5. Creates another workitem
        6. Verifies notifications continue to be received after reconnection
        """
        # Create a unique subscriber AE title
        aetitle = f"RECONNECT_AE_{uuid.uuid4().hex[:6]}"[:16]  # AE Titles are limited to 16 characters

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

            # First connection
            async with conductor.simulate_ws(ws_path) as ws:
                # Verify connection is established
                await ws.wait_ready()
                assert ws.ready, "WebSocket connection not ready"

                # Create a first workitem - should trigger notification
                response1 = await create_custom_workitem(conductor, sample_ups_workitem, priority="MEDIUM", state="SCHEDULED")
                assert response1.status_code == 201
                workitem1_uid = response1.json["00080018"]["Value"][0]
                print(f"Created workitem 1 with UID: {workitem1_uid}")

                # Wait for the notification about the first workitem
                try:
                    for i in range(2):
                        # Set a reasonable timeout for the test
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                        # Verify the notification contains correct data
                        assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                        assert msg["00001000"]["Value"][0] == workitem1_uid, "Incorrect workitem UID in notification"
                        assert "00741000" in msg, "Missing Procedure Step State in notification"
                        assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                        event_type_id = msg["00001002"]["Value"][0]
                        if event_type_id == 1:  # UPS State Report
                            print(f"Filtered subscriber received UPS State Report for {workitem1_uid} in iteration {i}")
                        elif event_type_id == 5:  # UPS Assigned
                            print(f"Filtered subscriber received UPS Assigned for {workitem1_uid} in iteration {i}")
                        else:
                            raise AssertionError(f"Unexpected event type ID: {event_type_id}")

                except TimeoutError as err:
                    raise AssertionError("No notification received for first workitem") from err

                # The first connection will be closed when we exit this context manager
                # which simulates a connection drop

            # Wait a short time to ensure the connection is fully closed
            await asyncio.sleep(1)

            # Reconnect with a new WebSocket connection
            async with conductor.simulate_ws(ws_path) as ws2:
                # Verify second connection is established
                await ws2.wait_ready()
                assert ws2.ready, "Second WebSocket connection not ready"

                # Existing UPS workitems will be notified on subscription, not on reconnection.
                # # Verify that existing UPS workitems are sent on reconnection
                # try:
                #     for i in range(2):
                #         # Set a reasonable timeout for the test
                #         msg = await asyncio.wait_for(ws2.receive_json(), timeout=5.0)

                #         # Verify the notification contains correct data
                #         assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                #         assert msg["00001000"]["Value"][0] == workitem1_uid, "Incorrect workitem UID in notification"
                #         assert "00741000" in msg, "Missing Procedure Step State in notification"
                #         assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                #         event_type_id = msg["00001002"]["Value"][0]
                #         if event_type_id == 1:  # UPS State Report
                #             print(f"Filtered subscriber received UPS State Report for {workitem1_uid} in iteration {i}")
                #         elif event_type_id == 5:  # UPS Assigned
                #             print(f"Filtered subscriber received UPS Assigned for {workitem1_uid} in iteration {i}")
                #         else:
                #             raise AssertionError(f"Unexpected event type ID: {event_type_id}")
                # except TimeoutError as err:
                #     raise AssertionError("No notification received for existing workitem on reconnection") from err

                # Create a second workitem after reconnection
                response2 = await create_custom_workitem(conductor, sample_ups_workitem, priority="HIGH", state="SCHEDULED")
                assert response2.status_code == 201
                workitem2_uid = response2.json["00080018"]["Value"][0]
                print(f"Created workitem 2 with UID: {workitem2_uid}")

                # Wait for the notification about the second workitem on the new connection
                try:
                    for i in range(2):
                        # Set a reasonable timeout for the test
                        msg = await asyncio.wait_for(ws2.receive_json(), timeout=5.0)

                        # Verify the notification contains correct data
                        assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                        assert msg["00001000"]["Value"][0] == workitem2_uid, "Incorrect workitem UID in notification"
                        assert "00741000" in msg, "Missing Procedure Step State in notification"
                        assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                        event_type_id = msg["00001002"]["Value"][0]
                        if event_type_id == 1:  # UPS State Report
                            print(f"Filtered subscriber received UPS State Report for {workitem2_uid} in iteration {i}")
                        elif event_type_id == 5:  # UPS Assigned
                            print(f"Filtered subscriber received UPS Assigned for {workitem2_uid} in iteration {i}")
                        else:
                            raise AssertionError(f"Unexpected event type ID: {event_type_id}")
                except TimeoutError as err:
                    raise AssertionError("No notification received for second workitem after reconnection") from err

                # Change state of the second workitem - should trigger another notification
                transaction_uid = str(generate_uid())
                payload = {
                    "00081195": {"vr": "UI", "Value": [transaction_uid]},
                    "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
                }
                payload_bytes = json.dumps(payload).encode("utf-8")

                response = await conductor.simulate_put(
                    f"/workitems/{workitem2_uid}/state",
                    body=payload_bytes,
                    headers={"Content-Type": "application/dicom+json"},
                )
                assert response.status_code == 200

                # Wait for the notification about the state change
                try:
                    # Set a reasonable timeout for the test
                    msg = await asyncio.wait_for(ws2.receive_json(), timeout=5.0)

                    # Verify the notification contains correct state
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "IN PROGRESS", "Incorrect state in notification"
                    event_type_id = msg["00001002"]["Value"][0]
                    if event_type_id == 1:  # UPS State Report
                        print(f"Filtered subscriber received UPS State Report for {workitem2_uid}")
                    else:
                        raise AssertionError(f"Unexpected event type ID: {event_type_id}")
                except TimeoutError as err:
                    raise AssertionError("No notification received for state change after reconnection") from err
