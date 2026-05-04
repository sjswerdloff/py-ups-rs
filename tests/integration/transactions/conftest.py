"""Fixtures for integration tests that require workitems in specific states."""

import json
from copy import deepcopy
from typing import Any

import pytest
from falcon.testing.client import TestClient
from pydicom.uid import generate_uid


@pytest.fixture
def created_workitem_uid(client: TestClient, sample_ups_workitem: dict[str, Any]) -> str:
    """Create a workitem and return its UID."""
    workitem = deepcopy(sample_ups_workitem)
    uid = str(generate_uid())
    workitem["00080018"]["Value"] = [uid]
    workitem["00741000"] = {"vr": "CS", "Value": ["SCHEDULED"]}

    payload_bytes = json.dumps(workitem).encode("utf-8")
    result = client.simulate_post("/workitems", body=payload_bytes, headers={"Content-Type": "application/dicom+json"})
    assert result.status_code == 201, f"Failed to create workitem: {result.status} {result.text}"
    return uid


@pytest.fixture
def in_progress_workitem_uid(client: TestClient, created_workitem_uid: str) -> tuple[str, str]:
    """
    Create a workitem and transition it to IN PROGRESS.

    Returns:
        Tuple of (workitem_uid, transaction_uid) — both needed for subsequent state changes.

    """
    transaction_uid = str(generate_uid())
    payload = {
        "00081195": {"vr": "UI", "Value": [transaction_uid]},
        "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    result = client.simulate_put(
        f"/workitems/{created_workitem_uid}/state",
        body=payload_bytes,
        headers={"Content-Type": "application/dicom+json"},
    )
    assert result.status_code == 200, f"Failed to change state to IN PROGRESS: {result.status} {result.text}"
    return created_workitem_uid, transaction_uid


@pytest.fixture
def subscribed_subscriber_uid(client: TestClient, created_workitem_uid: str) -> str:
    """Subscribe to a workitem and return the subscriber AE title."""
    ae_title = "TEST_SUBSCRIBER"
    payload = {
        "00741234": {"vr": "AE", "Value": [ae_title]},
        "0074120E": {"vr": "LT", "Value": ["ws://localhost:8080/subscribers/notifications"]},
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    result = client.simulate_post(
        f"/workitems/{created_workitem_uid}/subscribers/{ae_title}",
        body=payload_bytes,
        headers={"Content-Type": "application/dicom+json"},
    )
    assert result.status_code in (200, 201), f"Failed to subscribe: {result.status} {result.text}"
    return ae_title
