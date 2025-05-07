"""Integration test for DICOMWeb UPS-RS Filtered Subscription with Multiple Criteria."""

import asyncio
import json
import uuid
from copy import deepcopy
from typing import Any

import pytest
from falcon import Response
from falcon.testing import ASGIConductor, TestClient
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


@pytest.mark.asyncio(loop_scope="function")
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
class TestFilteredSubscriptionMultipleCriteria:
    """Test case for UPS-RS Filtered Subscription with Multiple Criteria."""

    async def test_filtered_subscription_multiple_criteria(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
    ) -> None:
        """
        Test subscription filtered on multiple criteria.

        This test:
        1. Creates a filtered subscription using multiple criteria (state and priority)
        2. Establishes a WebSocket connection
        3. Creates workitems with different combinations of state and priority
        4. Verifies notifications are only received for workitems matching all filter criteria
        """
        # Create a unique subscriber AE title
        aetitle = f"MULTI_FILTER_AE_{uuid.uuid4().hex[:6]}"[:16]  # AE Titles are limited to 16 characters

        # Filtered subscription well-known UID
        filtered_uid = FILTERED_SUBSCRIPTION_UID

        # Use ASGIConductor for WebSocket testing
        async with client as conductor:
            # Create a filtered subscription with multiple criteria
            # In this case, we're filtering on:
            # 1. Procedure Step State (00741000) = SCHEDULED
            # 2. Scheduled Procedure Step Priority (00741200) = HIGH

            # Since we can only use one filter value at a time in the query parameter,
            # we'll use multiple filter parameters
            filter_params = {
                "00741000": "SCHEDULED",  # Filter for SCHEDULED state
                "00741200": "HIGH",  # Filter for HIGH priority
            }

            # Build filter parameter string
            filter_str = ",".join([f"{key}={value}" for key, value in filter_params.items()])
            endpoint = f"/workitems/{filtered_uid}/subscribers/{aetitle}?filter={filter_str}"

            response = await conductor.simulate_post(
                endpoint,
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

                # Test Case 1: Create a workitem that matches BOTH criteria (SCHEDULED + HIGH priority)
                # Should receive notification
                response1 = await create_custom_workitem(conductor, sample_ups_workitem, priority="HIGH", state="SCHEDULED")
                assert response1.status_code == 201
                workitem1_uid = response1.json["00080018"]["Value"][0]
                print(f"Created workitem 1 (matching both criteria) with UID: {workitem1_uid}")

                # Wait for the notification about the first workitem
                try:
                    # Set a reasonable timeout for the test
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                    # Verify the notification contains correct data
                    assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                    assert msg["00001000"]["Value"][0] == workitem1_uid, "Incorrect workitem UID in notification"
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                except TimeoutError as err:
                    raise AssertionError("No notification received for workitem matching both criteria") from err

                # Test Case 2: Create a workitem that matches only the STATE criteria (SCHEDULED + MEDIUM priority)
                # Should NOT receive notification
                response2 = await create_custom_workitem(conductor, sample_ups_workitem, priority="MEDIUM", state="SCHEDULED")
                assert response2.status_code == 201
                workitem2_uid = response2.json["00080018"]["Value"][0]
                print(f"Created workitem 2 (matching only state) with UID: {workitem2_uid}")

                # Try to receive a notification for the second workitem - should timeout
                try:
                    # Set a shorter timeout for the test
                    await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    raise AssertionError("Received notification for workitem only matching state criteria")
                except TimeoutError:
                    # This is the expected behavior - no message should be received
                    pass

                # Test Case 3: Create a workitem that matches only the PRIORITY criteria (IN PROGRESS + HIGH priority)
                # Should NOT receive notification
                response3 = await create_custom_workitem(conductor, sample_ups_workitem, priority="HIGH", state="IN PROGRESS")
                assert response3.status_code == 201
                workitem3_uid = response3.json["00080018"]["Value"][0]
                print(f"Created workitem 3 (matching only priority) with UID: {workitem3_uid}")

                # Try to receive a notification for the third workitem - should timeout
                try:
                    # Set a shorter timeout for the test
                    await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    raise AssertionError("Received notification for workitem only matching priority criteria")
                except TimeoutError:
                    # This is the expected behavior - no message should be received
                    pass

                # Test Case 4: Create another workitem that matches BOTH criteria (SCHEDULED + HIGH priority)
                # Should receive notification
                response4 = await create_custom_workitem(conductor, sample_ups_workitem, priority="HIGH", state="SCHEDULED")
                assert response4.status_code == 201
                workitem4_uid = response4.json["00080018"]["Value"][0]
                print(f"Created workitem 4 (matching both criteria) with UID: {workitem4_uid}")

                # Wait for the notification about the fourth workitem
                try:
                    # Set a reasonable timeout for the test
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

                    # Verify the notification contains correct data
                    assert "00001000" in msg, "Missing Affected SOP Instance UID in notification"
                    assert msg["00001000"]["Value"][0] == workitem4_uid, "Incorrect workitem UID in notification"
                    assert "00741000" in msg, "Missing Procedure Step State in notification"
                    assert msg["00741000"]["Value"][0] == "SCHEDULED", "Incorrect state in notification"
                except TimeoutError as err:
                    raise AssertionError("No notification received for second workitem matching both criteria") from err
