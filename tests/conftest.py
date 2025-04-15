"""
Pytest configuration for DICOMWeb UPS-RS service testing with Falcon 4.0.2 ASGI.

This module provides fixtures for testing a DICOMweb UPS-RS (Unified Procedure Step) service
based on DICOM PS3.18 standard, running on Falcon 4.0.2 with ASGI/Uvicorn.

"""

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta
from typing import Any, Optional

import pytest
from falcon.asgi import App
from httpx import AsyncClient
from pydicom.uid import generate_uid


@pytest.fixture
def falcon_app() -> App:
    """
    Create and return a Falcon ASGI application instance for DICOMWeb UPS-RS.

    Returns:
        A Falcon ASGI application instance to be used for testing.

    Note:
        This is a placeholder fixture. You should customize this fixture
        to return your actual UPS-RS application instance with all routes
        and middleware configured.

    """
    app = App()

    # Add your UPS-RS resources here
    # Example:
    from pyupsrs.api.resources.subscriptions import SubscriptionResource, SubscriptionSuspendResource
    from pyupsrs.api.resources.workitems import WorkItemResource, WorkItemsResource, WorkItemStateResource

    # the same variable name has to be used in routes that are children of the same parent.
    # so workitem_uid for subscribers is necessary, and needs to be interpreted as
    # a resource ID (well known UIDs for Global and Filtered )

    app.add_route("/workitems/{workitem_uid}/subscribers/{aetitle}/suspend", SubscriptionSuspendResource())
    app.add_route("/workitems/{workitem_uid}/subscribers/{aetitle}", SubscriptionResource())
    app.add_route("/workitems/{workitem_uid}/state", WorkItemStateResource())
    app.add_route("/workitems/{workitem_uid}", WorkItemResource())
    app.add_route("/workitems", WorkItemsResource())
    return app


@pytest.fixture
async def client(falcon_app: App) -> AsyncGenerator[AsyncClient, None]:
    """
    Create a test client for DICOMWeb services using HTTPX.

    Args:
        falcon_app: The Falcon ASGI application instance to test.

    Yields:
        An HTTPX AsyncClient instance configured for the application.

    """
    # config = uvicorn_config()
    host = "localhost"  # config["host"]
    port = 8000  # config["port"]
    my_url = f"http://{host}:{port}"

    async with AsyncClient(base_url=my_url) as client:
        yield client


@pytest.fixture
def dicom_auth_header() -> dict[str, str]:
    """
    Generate authentication headers for DICOMWeb services.

    Returns:
        A dictionary containing authentication headers.

    """
    # DICOMweb commonly uses Bearer tokens or Basic Auth
    # Example for JWT:
    # token = "your_jwt_token_here"
    # return {"Authorization": f"Bearer {token}"}

    # Example for Basic Auth:
    # import base64
    # credentials = base64.b64encode(b"dicom_user:dicom_password").decode("utf-8")
    # return {"Authorization": f"Basic {credentials}"}

    return {}


@pytest.fixture
def dicom_headers() -> dict[str, str]:
    """
    Create common DICOMWeb headers.

    Returns:
        A dictionary of standard DICOMWeb headers.

    """
    return {
        "Accept": "application/dicom+json",
        "Content-Type": "application/dicom+json",
    }


@pytest.fixture
def dicom_multipart_headers() -> dict[str, str]:
    """
    Create multipart related DICOMWeb headers.

    Returns:
        A dictionary of DICOMWeb headers for multipart requests.

    """
    boundary = "boundary_" + str(uuid.uuid4()).replace("-", "")

    return {
        "Accept": "multipart/related; type=application/dicom+xml",
        "Content-Type": f"multipart/related; type=application/dicom+json; boundary={boundary}",
    }


@pytest.fixture
def sample_ups_workitem() -> dict[str, Any]:
    """
    Create a sample UPS workitem for testing.

    Returns:
        A dictionary containing a minimal valid UPS workitem.

    """
    return {
        "00080016": {"vr": "UI", "Value": ["1.2.840.10008.5.1.4.34.6.1"]},  # SOP Class UID (UPS Push)
        "00080018": {"vr": "UI", "Value": [f"{generate_uid()}"]},  # SOP Instance UID
        "00080054": {"vr": "AE", "Value": ["TESTSTATION"]},  # Retrieve AE Title
        "00080056": {"vr": "CS", "Value": ["TESTMODALITY"]},  # Instance Availability
        "00100010": {"vr": "PN", "Value": [{"Alphabetic": "TEST^PATIENT"}]},  # Patient Name
        "00100020": {"vr": "LO", "Value": ["TEST-ID-123"]},  # Patient ID
        "00100030": {"vr": "DA", "Value": ["20230101"]},  # Patient Birth Date
        "00404041": {"vr": "CS", "Value": ["SCHEDULED"]},  # Input Readiness State
        "00404005": {"vr": "DT", "Value": [(datetime.now()).strftime("%Y%m%d%H%M%S")]},  # Scheduled Start DateTime
        "00404010": {
            "vr": "DT",
            "Value": [(datetime.now() + timedelta(hours=1)).strftime("%Y%m%d%H%M%S")],
        },  # Scheduled Processing End DateTime
        "00404025": {
            "vr": "SQ",
            "Value": [  # Scheduled Station Name Code
                {
                    "00080100": {"vr": "SH", "Value": ["TEST_STATION"]},  # Code Value
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},  # Coding Scheme Designator
                    "00080104": {"vr": "LO", "Value": ["Test Station"]},  # Code Meaning
                }
            ],
        },
        "00404026": {
            "vr": "SQ",
            "Value": [  # Scheduled Station Class Code
                {
                    "00080100": {"vr": "SH", "Value": ["TEST_STATION_CLASS"]},  # Code Value
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},  # Coding Scheme Designator
                    "00080104": {"vr": "LO", "Value": ["Test Station Class"]},  # Code Meaning
                }
            ],
        },
        "00404027": {
            "vr": "SQ",
            "Value": [  # Scheduled Station Geographic Location Code
                {
                    "00080100": {"vr": "SH", "Value": ["TEST_LOCATION"]},  # Code Value
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},  # Coding Scheme Designator
                    "00080104": {"vr": "LO", "Value": ["Test Location"]},  # Code Meaning
                }
            ],
        },
        "00404018": {
            "vr": "SQ",
            "Value": [  # Scheduled Workitem Code
                {
                    "00080100": {"vr": "SH", "Value": ["TEST_WORKITEM"]},  # Code Value
                    "00080102": {"vr": "SH", "Value": ["99TEST"]},  # Coding Scheme Designator
                    "00080104": {"vr": "LO", "Value": ["Test Workitem"]},  # Code Meaning
                }
            ],
        },
        "00741000": {"vr": "CS", "Value": ["SCHEDULED"]},  # Procedure Step State
    }


@pytest.fixture
def ups_state_report() -> dict[str, Any]:
    """
    Create a sample UPS state report for testing.

    Returns:
        A dictionary containing a UPS state report.

    """
    return {
        "00080016": {"vr": "UI", "Value": ["1.2.840.10008.5.1.4.34.6.1"]},  # SOP Class UID (UPS Push)
        "00080018": {"vr": "UI", "Value": [f"{generate_uid}"]},  # SOP Instance UID
        "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},  # Procedure Step State
        "00741002": {
            "vr": "SQ",
            "Value": [  # Procedure Step Progress
                {
                    "00741004": {"vr": "DS", "Value": ["50"]},  # Procedure Step Progress (Percentage)
                    "00741006": {"vr": "ST", "Value": ["Processing test data"]},  # Procedure Step Progress Description
                }
            ],
        },
    }


@pytest.fixture
def ups_subscription_request() -> dict[str, Any]:
    """
    Create a sample UPS subscription request for testing.

    Returns:
        A dictionary containing a UPS subscription request.

    """
    return {
        "00741234": {"vr": "AE", "Value": ["SUBSCRIBER_AET"]},  # Receiving AE
        "00741000": {"vr": "CS", "Value": ["IN PROGRESS", "COMPLETED"]},  # Procedure Step State
    }


@pytest.fixture
def ups_search_params() -> dict[str, str]:
    """
    Create sample DICOMWeb UPS-RS search parameters.

    Returns:
        A dictionary of common UPS-RS search parameters.

    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")

    return {
        "PatientName": "TEST*",
        "PatientID": "TEST-ID-123",
        "ProcedureStepState": "SCHEDULED,IN PROGRESS",
        "ScheduledProcedureStepStartDateTime": f"{yesterday}-{tomorrow}",
        "WorklistLabel": "TEST-WORKLIST",
    }


@pytest.fixture
def create_ups_filter_params() -> Callable[..., str]:
    """
    Create a factory function to generate UPS-RS filter parameters.

    Returns:
        A callable that creates UPS-RS filter parameters.

    """

    def _create_params(
        patient_id: Optional[str] = None,
        patient_name: Optional[str] = None,
        state: Optional[list[str]] = None,
        start_date_range: Optional[tuple[str, str]] = None,
        scheduled_aet: Optional[str] = None,
        worklist_label: Optional[str] = None,
    ) -> str:
        """
        Create UPS-RS filter parameters string.

        Args:
            patient_id: Patient ID to filter by
            patient_name: Patient name pattern to filter by
            state: List of procedure step states to filter by
            start_date_range: Tuple of (start, end) dates for scheduled start time
            scheduled_aet: Scheduled AE Title to filter by
            worklist_label: Worklist label to filter by

        Returns:
            A query string for UPS-RS filtering

        """
        params = []

        if patient_id:
            params.append(f"PatientID={patient_id}")

        if patient_name:
            params.append(f"PatientName={patient_name}")

        if state:
            params.append(f"ProcedureStepState={','.join(state)}")

        if start_date_range:
            params.append(f"ScheduledProcedureStepStartDateTime={start_date_range[0]}-{start_date_range[1]}")

        if scheduled_aet:
            params.append(f"ScheduledStationAETitle={scheduled_aet}")

        if worklist_label:
            params.append(f"WorklistLabel={worklist_label}")

        return "&".join(params)

    return _create_params


@pytest.fixture
async def mock_dicom_db_session() -> AsyncGenerator[None, None]:
    """
    Create a mock database session for DICOM storage testing.

    Yields:
        None

    Note:
        This is a placeholder fixture. You should customize this fixture
        to create and provide a real database session appropriate for
        your DICOM storage (MongoDB, PostgreSQL, etc.).

    """
    # Example for MongoDB with Motor:
    # from motor.motor_asyncio import AsyncIOMotorClient
    #
    # client = AsyncIOMotorClient("mongodb://localhost:27017")
    # db = client.test_dicom_db
    #
    # # Clear test collections
    # await db.workitems.delete_many({})
    # await db.subscriptions.delete_many({})
    #
    # yield db
    #
    # # Clean up after tests
    # await db.workitems.delete_many({})
    # await db.subscriptions.delete_many({})

    # For now, just yield None as a placeholder
    yield None


@pytest.fixture
def uvicorn_config() -> dict[str, Any]:
    """
    Define Uvicorn server configuration for testing.

    Returns:
        A dictionary with Uvicorn configuration parameters.

    """
    return {
        "host": "127.0.0.1",
        "port": 8000,
        "log_level": "error",
        "timeout_keep_alive": 5,
        "limit_concurrency": 100,
        "limit_max_requests": 0,
        "workers": 1,
    }
