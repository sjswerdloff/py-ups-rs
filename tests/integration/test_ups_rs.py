"""
Tests for DICOMWeb UPS-RS service.

This module contains tests for a DICOMWeb UPS-RS (Unified Procedure Step) service
based on DICOM PS3.18 standard.

"""
import json
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_workitem(
    client: AsyncClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
) -> None:
    """
    Test creating a new UPS workitem.

    Args:
        client: HTTPX AsyncClient for making requests
        sample_ups_workitem: Test UPS workitem data
        dicom_headers: DICOM HTTP headers

    """
    response = await client.post("/workitems", json=sample_ups_workitem, headers=dicom_headers)

    assert response.status_code == 201  # Created

    # Verify response contains the created workitem UID
    response_data = response.json()
    assert "00080018" in response_data  # SOP Instance UID


@pytest.mark.asyncio
async def test_get_workitem(client: AsyncClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]) -> None:
    """
    Test retrieving a specific UPS workitem.

    Args:
        client: HTTPX AsyncClient for making requests
        sample_ups_workitem: Test UPS workitem data
        dicom_headers: DICOM HTTP headers

    """
    # First, create a workitem to ensure it exists
    create_response = await client.post("/workitems", json=sample_ups_workitem, headers=dicom_headers)
    created_workitem = create_response.json()
    print(type(created_workitem))
    workitem_uid = created_workitem["00080018"]["Value"][0]

    # Then retrieve it
    response = await client.get(f"/workitems/{workitem_uid}", headers=dicom_headers)

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/dicom+json"

    retrieved_workitem = response.json()
    print(type(retrieved_workitem))
    assert retrieved_workitem["00080018"]["Value"][0] == workitem_uid
    assert retrieved_workitem["00741000"]["Value"][0] == "SCHEDULED"  # Initial state should be SCHEDULED


@pytest.mark.asyncio
async def test_change_state(client: AsyncClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]) -> None:
    """
    Test changing the state of a UPS workitem.

    Args:
        client: HTTPX AsyncClient for making requests
        sample_ups_workitem: Test UPS workitem data
        dicom_headers: DICOM HTTP headers

    """
    # First, create a workitem to ensure it exists
    create_response = await client.post("/workitems", json=sample_ups_workitem, headers=dicom_headers)
    created_workitem = create_response.json()
    workitem_uid = created_workitem["00080018"]["Value"][0]

    # Then change its state to IN PROGRESS
    state_report = {"00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
                    "00081195": {"vr": "UI", "Value": ["1.2.3.4.5.6.7.8.9"]}}

    response = await client.put(f"/workitems/{workitem_uid}/state", json=state_report, headers=dicom_headers)

    assert response.status_code == 200

    # Verify the state was changed
    get_response = await client.get(f"/workitems/{workitem_uid}", headers=dicom_headers)

    updated_workitem = get_response.json()
    assert updated_workitem["00741000"]["Value"][0] == "IN PROGRESS"


@pytest.mark.asyncio
async def test_search_workitems(
    client: AsyncClient, sample_ups_workitem: dict[str, Any], create_ups_filter_params: Callable, dicom_headers: dict[str, str]
) -> None:
    """
    Test searching for UPS workitems with filters.

    Args:
        client: HTTPX AsyncClient for making requests
        sample_ups_workitem: Test UPS workitem data
        create_ups_filter_params: Function to create filter parameters
        dicom_headers: DICOM HTTP headers

    """
    # First, create a workitem to ensure we have at least one
    await client.post("/workitems", json=sample_ups_workitem, headers=dicom_headers)

    # Search for workitems with specified criteria
    query = create_ups_filter_params(patient_name="TEST*", state=["SCHEDULED"])

    response = await client.get(f"/workitems?{query}", headers=dicom_headers)

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/dicom+json"

    # Parse the response and check that at least one workitem is returned
    results = response.json()
    assert isinstance(results, list)
    assert len(results) > 0


@pytest.mark.asyncio
async def test_subscribe_to_workitem(
    client: AsyncClient,
    sample_ups_workitem: dict[str, Any],
    ups_subscription_request: dict[str, Any],
    dicom_headers: dict[str, str],
) -> None:
    """
    Test subscribing to state changes for a UPS workitem.

    Args:
        client: HTTPX AsyncClient for making requests
        sample_ups_workitem: Test UPS workitem data
        ups_subscription_request: Subscription request data
        dicom_headers: DICOM HTTP headers

    """
    # First, create a workitem to ensure it exists
    create_response = await client.post("/workitems", json=sample_ups_workitem, headers=dicom_headers)
    created_workitem = create_response.json()
    workitem_uid = created_workitem["00080018"]["Value"][0]

    # Subscribe to state changes
    subscriber_aet = "SUBSCRIBER_AET"

    response = await client.post(
        f"/workitems/{workitem_uid}/subscribers/{subscriber_aet}", json=ups_subscription_request, headers=dicom_headers
    )

    assert response.status_code == 201  # Created

    # # Verify the subscription was created
    # get_response = await client.get(f"/workitems/{workitem_uid}/subscribers/{subscriber_aet}", headers=dicom_headers)

    # assert get_response.status_code == 200


@pytest.mark.asyncio
async def test_unsubscribe_from_workitem(
    client: AsyncClient,
    sample_ups_workitem: dict[str, Any],
    ups_subscription_request: dict[str, Any],
    dicom_headers: dict[str, str],
) -> None:
    """
    Test unsubscribing from state changes for a UPS workitem.

    Args:
        client: HTTPX AsyncClient for making requests
        sample_ups_workitem: Test UPS workitem data
        ups_subscription_request: Subscription request data
        dicom_headers: DICOM HTTP headers

    """
    # First, create a workitem to ensure it exists
    create_response = await client.post("/workitems", json=sample_ups_workitem, headers=dicom_headers)
    created_workitem = create_response.json()
    workitem_uid = created_workitem["00080018"]["Value"][0]

    # Subscribe to state changes
    subscriber_aet = "SUBSCRIBER_AET"

    await client.post(
        f"/workitems/{workitem_uid}/subscribers/{subscriber_aet}", json=ups_subscription_request, headers=dicom_headers
    )

    # Then unsubscribe
    delete_response = await client.delete(f"/workitems/{workitem_uid}/subscribers/{subscriber_aet}", headers=dicom_headers)

    assert delete_response.status_code == 200

    # # Verify the subscription was removed
    # get_response = await client.get(f"/workitems/{workitem_uid}/subscribers/{subscriber_aet}", headers=dicom_headers)

    # assert get_response.status_code == 404  # Not Found


@pytest.mark.asyncio
async def test_cancel_workitem(
    client: AsyncClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]
) -> None:
    """
    Test cancelling a UPS workitem.

    Args:
        client: HTTPX AsyncClient for making requests
        sample_ups_workitem: Test UPS workitem data
        dicom_headers: DICOM HTTP headers

    """
    # First, create a workitem to ensure it exists
    create_response = await client.post("/workitems", json=sample_ups_workitem, headers=dicom_headers)
    created_workitem = create_response.json()
    workitem_uid = created_workitem["00080018"]["Value"][0]

    # Cancel the workitem
    cancel_request = {
        "00741000": {"vr": "CS", "Value": ["CANCELED"]},
        "00741002": {"vr": "SQ", "Value": [{"00741006": {"vr": "ST", "Value": ["Test cancellation reason"]}}]},
    }

    response = await client.post(f"/workitems/{workitem_uid}/cancelrequest", json=cancel_request, headers=dicom_headers)

    assert response.status_code == 202

    # Verify the workitem was cancelled
    get_response = await client.get(f"/workitems/{workitem_uid}", headers=dicom_headers)

    canceled_workitem = get_response.json()
    assert canceled_workitem["00741000"]["Value"][0] == "CANCELED"
