"""Integration test for creating a UPS workitem."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import pytest
from falcon import Response
from falcon.testing.client import TestClient
from pydicom.uid import generate_uid

from pyupsrs.utils.dicom_query_matcher import parse_dicom_date


def create_workitem_helper(client: TestClient, sample_ups_workitem: dict[str, Any]) -> Response:
    """Create a workitem."""
    # Prepare test data
    payload = sample_ups_workitem
    specified_instance_uid_list: list = payload["00080018"]["Value"]
    specified_instance_uid = specified_instance_uid_list[0]
    print(f"Instance UID: {type(specified_instance_uid)} = {specified_instance_uid}")
    json_payload = json.dumps(payload)
    payload_bytes = json_payload.encode("utf-8")
    # Send request

    return client.simulate_post("/workitems", body=payload_bytes, headers={"Content-Type": "application/dicom+json"})


def retrieve_workitem_helper(client: TestClient, specified_instance_uid: str) -> Response:
    """Retrieve a workitem."""
    location = f"/workitems/{specified_instance_uid}"
    return client.simulate_get(location, headers={"Accept": "application/dicom+json"})


def search_workitem_helper(
    client: TestClient,
    match_parameters: dict[str, str],
    include_fields: list[str] | None = None,
    fuzzy_matching: bool = False,
    offset: int = 0,
    limit: int | None = None,
    no_cache: bool = False,
) -> Response:
    """Search for workitems."""
    params = dict(match_parameters)
    # Add include fields if provided
    if include_fields:
        for field in include_fields:
            if "includefield" in params:
                params["includefield"] += f",{field}"
            else:
                params["includefield"] = field

    # Add fuzzy matching if enabled
    if fuzzy_matching:
        params["fuzzymatching"] = "true"

    # Add paging parameters if provided
    params["offset"] = str(offset)
    if limit is not None:
        params["limit"] = str(limit)

    # Set endpoint URL with query parameters
    endpoint = f"/workitems?{urlencode(params, doseq=True)}"

    # Set headers
    headers = {"Accept": "application/dicom+json"}

    # Add Cache-Control header if no_cache is True
    if no_cache:
        headers["Cache-Control"] = "no-cache"
    return client.simulate_get(endpoint, headers=headers)


def change_state_helper(client: TestClient, created_workitem_uid: str, transaction_uid: str, state: str) -> Response:
    """Change a workitem state to IN PROGRESS."""
    # Prepare test data
    payload = {"00081195": {"vr": "UI", "Value": [transaction_uid]}, "00741000": {"vr": "CS", "Value": [state]}}

    location = f"/workitems/{created_workitem_uid}/state"
    payload_bytes = json.dumps(payload).encode("utf-8")
    # Send request
    return client.simulate_put(location, body=payload_bytes, headers={"Content-Type": "application/dicom+json"})


def update_workitem_helper(client: TestClient, created_workitem_uid: str, sample_schedule_update: dict[str, Any]) -> Response:
    """Update a workitem."""
    # Prepare test data

    payload = {"00741000": {"vr": "UI", "Value": [created_workitem_uid]}}
    payload.update(sample_schedule_update)

    payload_bytes = json.dumps(payload).encode("utf-8")
    # Send request
    return client.simulate_put(
        f"/workitems/{created_workitem_uid}", body=payload_bytes, headers={"Content-Type": "application/dicom+json"}
    )


def cancel_workitem_helper(client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, str]) -> Response:
    """
    Request cancellation of a UPS workitem.

    Args:
        client: Falcon TestClient for making requests
        sample_ups_workitem: Test UPS workitem data
        dicom_headers: DICOM HTTP headers

    """
    payload = sample_ups_workitem
    specified_instance_uid_list: list = payload["00080018"]["Value"]
    workitem_uid = specified_instance_uid_list[0]

    # Request the Cancellation of the workitem
    cancel_request = {
        "00741000": {"vr": "CS", "Value": ["CANCELED"]},
        "00741002": {"vr": "SQ", "Value": [{"00741006": {"vr": "ST", "Value": ["Test cancellation reason"]}}]},
    }

    payload_bytes = json.dumps(cancel_request).encode("utf-8")

    return client.simulate_post(f"/workitems/{workitem_uid}/cancelrequest", body=payload_bytes, headers=dicom_headers)


@pytest.mark.integration
class TestWorkitemTransactions:
    """Test case for creating a UPS workitem."""

    def test_create_and_retrieve_workitem(
        self,
        client: TestClient,
        sample_ups_workitem: dict[str, Any],
    ) -> None:
        """
        Test creating a workitem.

        As part of testing that the CREATE transaction was a success,
        also tests the RETRIEVE transaction
        """
        # Send request

        result = create_workitem_helper(client, sample_ups_workitem)
        # Verify response is that it got created
        assert result.status_code == 201

        payload = sample_ups_workitem
        specified_instance_uid_list: list = payload["00080018"]["Value"]
        specified_instance_uid = specified_instance_uid_list[0]

        location = f"/workitems/{specified_instance_uid}"
        print(location)
        # Verify the workitem exists
        result = retrieve_workitem_helper(client, specified_instance_uid)
        # result = client.simulate_get(location, headers={"Accept": "application/dicom+json"})
        assert result.status_code == 200
        # Verify that the Procedure Step Status is appropriate for having just
        # been created, namely "SCHEDULED"
        assert result.json["00741000"]["Value"][0] == "SCHEDULED"

    def test_change_state_in_progress(self, client: TestClient, sample_ups_workitem: dict[str, Any]) -> None:
        """Test that state changes to IN PROGRESS."""
        result = create_workitem_helper(client, sample_ups_workitem)
        # make sure it got created
        assert result.status_code == 201
        payload = sample_ups_workitem
        specified_instance_uid_list: list = payload["00080018"]["Value"]
        specified_instance_uid = specified_instance_uid_list[0]
        transaction_uid: str = str(generate_uid())
        workitem_state = "IN PROGRESS"
        result = change_state_helper(client, specified_instance_uid, transaction_uid, workitem_state)
        # Verify the change state request was honoured
        assert result.status_code == 200

        # Verify the state was changed to IN PROGRESS
        result = retrieve_workitem_helper(client, specified_instance_uid)
        assert result.status_code == 200
        assert result.json["00741000"]["Value"][0] == workitem_state

    def test_update_workitem_while_scheduled(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], sample_schedule_date_update: dict[str, Any]
    ) -> None:
        """Test Updating a Workitem while it's state is still SCHEDULED."""
        result = create_workitem_helper(client, sample_ups_workitem)
        assert result.status_code == 201
        payload = sample_ups_workitem
        specified_instance_uid_list: list = payload["00080018"]["Value"]
        specified_instance_uid = specified_instance_uid_list[0]
        # Verify the update request was honoured
        result = update_workitem_helper(client, specified_instance_uid, sample_schedule_date_update)
        assert result.status_code == 200
        # Verify the updated workitem contains the correct values
        result = retrieve_workitem_helper(client, specified_instance_uid)
        assert result.status_code == 200
        scheduled_start_datetime = sample_schedule_date_update["00404005"]["Value"][0]
        expected_completion_datetime = sample_schedule_date_update["00404011"]["Value"][0]
        assert result.json["00404005"]["Value"][0] == scheduled_start_datetime
        assert result.json["00404011"]["Value"][0] == expected_completion_datetime

    def test_request_workitem_cancellation_while_scheduled(
        self, client: TestClient, sample_ups_workitem: dict[str, Any], dicom_headers: dict[str, Any]
    ) -> None:
        """
        Test request workitem cancellation.

        Args:
            client (TestClient): Falcon test client as fixture
            sample_ups_workitem (dict[str, Any]): sample UPS create content
            dicom_headers (dict[str, Any]): the header values for what will be accepted and content type

        """
        result = create_workitem_helper(client, sample_ups_workitem)
        print(result)
        assert result.status_code == 201
        payload = sample_ups_workitem
        specified_instance_uid_list: list = payload["00080018"]["Value"]
        specified_instance_uid = specified_instance_uid_list[0]
        # Verify the cancellation request was honoured
        result = cancel_workitem_helper(client, sample_ups_workitem, dicom_headers)
        assert result.status_code == 202
        # Verify that the procedure step state is now "CANCELED"
        result = retrieve_workitem_helper(client, specified_instance_uid)
        assert result.status_code == 200
        assert result.json["00741000"]["Value"][0] == "CANCELED"

    def test_search_workitems(
        self,
        client: TestClient,
        sample_ups_workitem: dict[str, Any],
        dicom_headers: dict[str, Any],
    ) -> None:
        """
        Test workitems search.

        Args:
            client (TestClient): _description_
            sample_ups_workitem (dict[str, Any]): _description_
            dicom_headers (dict[str, Any]): _description_

        """
        # initial_scheduled_count = 0
        # initial_in_progress_count = 0
        #
        # Check to see what is already present.  Caching was taking place between tests.
        # until I added a reset of the internal repository of workitems
        # result = search_workitem_helper(client, match_parameters={"00741000": "SCHEDULED"}, no_cache=True)

        # if result.status_code == 200:
        #     workitems = result.json
        #     print(workitems)
        #     initial_scheduled_count = len(workitems)
        # print(f"Initial Scheduled Work Item Count = {initial_scheduled_count}")

        # result = search_workitem_helper(client, match_parameters={"00741000": "IN PROGRESS"}, no_cache=True)

        # if result.status_code == 200:
        #     workitems = result.json
        #     print(workitems)
        #     initial_in_progress_count = len(workitems)
        #     assert workitems[0]["00741000"]["Value"][0] == "IN PROGRESS"
        # print(f"Initial IN PROGRESS Work Item Count = {initial_in_progress_count}")

        # assert initial_scheduled_count == 0
        # assert initial_in_progress_count == 0
        # Create a workitem, and make sure it comes back in a search
        result = create_workitem_helper(client, sample_ups_workitem)
        assert result.status_code == 201
        result = search_workitem_helper(client, match_parameters={"00741000": "SCHEDULED"}, no_cache=True)
        assert result.status_code == 200
        workitems = result.json
        print(workitems)
        assert len(workitems) == 1  # + initial_scheduled_count
        assert workitems[0]["00741000"]["Value"][0] == "SCHEDULED"

        # Add another work item, make sure both come back
        second_work_item = deepcopy(sample_ups_workitem)
        second_work_item["00080018"]["Value"][0] = generate_uid()
        start_datetime: datetime = parse_dicom_date(second_work_item["00404005"]["Value"][0])
        start_datetime += timedelta(hours=1)
        second_work_item["00404005"]["Value"][0] = start_datetime.strftime("%Y%m%d%H%M%S")
        # if hasattr(second_work_item, "00404011") and hasattr(second_work_item["00404011"], "Value"):
        #     end_datetime: datetime = parse_dicom_date(second_work_item["00404011"]["Value"][0])
        #     end_datetime += timedelta(hours=1)
        #     second_work_item["00404011"]["Value"][0] = end_datetime.strftime("%Y%m%d%H%M%S")
        result = create_workitem_helper(client, second_work_item)
        assert result.status_code == 201
        result = search_workitem_helper(client, match_parameters={"00741000": "SCHEDULED"}, no_cache=True)
        assert result.status_code == 200
        workitems = result.json
        print(workitems)
        assert len(workitems) == 2  # + initial_scheduled_count

        # search for something that shouldn't have a match
        result = search_workitem_helper(client, match_parameters={"00741000": "IN PROGRESS"}, no_cache=True)
        assert result.status_code == 404
        # assert result.status_code in [200, 404]
        # if result.status_code == 200:
        #     workitems = result.json
        #     print(workitems)
        #     assert len(workitems) == initial_in_progress_count

        # add a test for include_field
        # and then refactor to parameterize the testing.
