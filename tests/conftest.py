"""Pytest fixtures."""

import os

import pytest
from falcon import testing

import pyupsrs.app as app


@pytest.fixture
def client() -> testing.TestClient:
    """Create a Falcon test client."""
    # Use an in-memory database for testing
    os.environ["PYUPSRS_DATABASE_URI"] = "sqlite:///:memory:"
    os.environ["PYUPSRS_DEBUG"] = "true"

    # Create the Falcon app
    api = app.create_app()

    # Create and return a test client
    return testing.TestClient(api)


@pytest.fixture
def created_workitem_uid(client: testing.TestClient) -> str:
    """Create a workitem and return its UID."""
    # Prepare test data
    workitem_uid = "1.2.826.0.1.3680043.9.7133.1.1"
    payload = [
        {
            "00741000": {"vr": "UI", "Value": [workitem_uid]},
            "00404005": {"vr": "DT", "Value": ["20220101120000"]},
            "00404011": {"vr": "DT", "Value": ["20220101130000"]},
            "00741200": {"vr": "CS", "Value": ["SCHEDULED"]},
        }
    ]

    # Create the workitem
    client.simulate_post("/workitems", json=payload, headers={"Content-Type": "application/dicom+json"})

    return workitem_uid


@pytest.fixture
def in_progress_workitem_uid(client: testing.TestClient, created_workitem_uid: str) -> str:
    """Create a workitem in IN PROGRESS state and return its UID."""
    # Prepare test data
    payload = [{"00741000": {"vr": "UI", "Value": [created_workitem_uid]}, "00741200": {"vr": "CS", "Value": ["IN PROGRESS"]}}]

    # Update the workitem state
    client.simulate_put(
        f"/workitems/{created_workitem_uid}/state", json=payload, headers={"Content-Type": "application/dicom+json"}
    )

    return created_workitem_uid


@pytest.fixture
def subscribed_subscriber_uid(client: testing.TestClient, created_workitem_uid: str) -> str:
    """Create a subscription and return the subscriber UID."""
    subscriber_uid = "1.2.826.0.1.3680043.9.7133.2.1"
    payload = [
        {
            "00741000": {"vr": "UI", "Value": [created_workitem_uid]},
            "00741234": {"vr": "UI", "Value": [subscriber_uid]},
            "0074120E": {"vr": "LT", "Value": ["ws://localhost:8080/subscribers/notifications"]},
        }
    ]

    # Create the subscription
    client.simulate_post(
        f"/workitems/{created_workitem_uid}/subscribers", json=payload, headers={"Content-Type": "application/dicom+json"}
    )

    return subscriber_uid
