"""Falcon resources for UPS workitems."""

import json
from typing import Any

import falcon
from falcon.asgi import BoundedStream

from pyupsrs.api.serializers.dicom_json import deserialize_workitem
from pyupsrs.config import Config
from pyupsrs.domain.services import workitem_service
from pyupsrs.storage.repositories import workitem_repository


# Custom media handler for application/dicom+json
class DICOMJSONHandler:
    """Handler for application/dicom+json media type."""

    def deserialize(self, stream: BoundedStream, content_type: str, content_length: int) -> dict[str, Any]:
        """
        Deserialize the request body from application/dicom+json.

        Args:
            stream: The request body stream.
            content_type: The content type of the request.
            content_length: The length of the request body.

        Returns:
            The parsed request body.

        """
        body = stream.read(content_length or 0)
        return json.loads(body) if body else {}

    def serialize(self, media: dict[str, Any], content_type: str) -> bytes:
        """
        Serialize the media object to application/dicom+json.

        Args:
            media: The media object to serialize.
            content_type: The content type to serialize to.

        Returns:
            The serialized media.

        """
        return json.dumps(media).encode("utf-8")


class WorkItemsResource:
    """Resource for handling collections of UPS workitems."""

    def __init__(self, workitem_service: workitem_service = None) -> None:
        """
        Initialize the resource.

        Args:
            workitem_service: Service for handling workitem operations.

        """
        self.workitem_service = workitem_service

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """
        Handle GET requests to retrieve a collection of workitems.

        Args:
            req: The HTTP request.
            resp: The HTTP response.

        """
        # TODO: Implement workitem query
        resp.media = {"workitems": []}
        resp.content_type = "application/dicom+json"
        resp.status = falcon.HTTP_200

    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """
        Handle POST requests to create a new workitem.

        Args:
            req: The HTTP request.
            resp: The HTTP response.

        """
        try:
            # Manually read and parse the request body
            body = await req.stream.read()
            if not body:
                raise falcon.HTTPBadRequest(title="Empty request body", description="A valid DICOM JSON dataset is required")

            # Parse the JSON body
            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                raise falcon.HTTPBadRequest(title="Invalid JSON", description="Request body must be valid JSON") from e

            json_dicom = data
            workitem = deserialize_workitem(json_dicom)

            workitem_crud = workitem_repository.WorkItemRepository(database_uri=Config.database_uri)
            db_service = workitem_service.WorkItemService(workitem_repository=workitem_crud, notification_service=None)
            db_service.create_workitem(workitem=workitem)
            workitem_response = {"00080018": {"Value": [workitem.SOPInstanceUID], "vr": "UI"}}

            resp.status = falcon.HTTP_201
            resp.content_type = "application/dicom+json"
            resp_media = json.dumps(workitem_response)
            resp.text = resp_media

        except Exception as e:
            # Log the exception
            raise falcon.HTTPInternalServerError(title="Error processing request", description=str(e)) from e


class WorkItemResource:
    """Resource for handling individual UPS workitems."""

    async def on_get(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
        """
        Handle GET requests to retrieve a specific workitem.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.

        """
        # TODO: Implement workitem retrieval
        resp.media = {"workitem_uid": workitem_uid}
        resp.content_type = "application/dicom+json"
        resp.status = falcon.HTTP_200

    async def on_put(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
        """
        Handle PUT requests to update a workitem.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.

        """
        # TODO: Implement workitem update
        resp.status = falcon.HTTP_200
        resp.content_type = "application/dicom+json"
