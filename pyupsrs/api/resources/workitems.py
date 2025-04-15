"""Falcon resources for UPS workitems."""

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
import falcon
from falcon.asgi import BoundedStream

from pydicom import Dataset, DataElement, datadict

from pyupsrs.api.serializers.dicom_json import deserialize_workitem
from pyupsrs.config import Config
from pyupsrs.domain.models.ups import WorkItemStatus
from pyupsrs.domain.services import workitem_service as svc_workitem_service
from pyupsrs.storage.repositories import workitem_repository
from pyupsrs.utils.class_logger import LoggerMixin

UPS_WARNING_MODIFICATIONS = "Warning: 299 {service}: The Workitem was updated with modifications."
UPS_WARNING_URI_UNCLAIMED_WORKITEM = "Warning: 299 {service}: The target URI did not reference a claimed Workitem."
UPS_WARNING_INCONSISTENT_WITH_STATE = (
    "Warning: 299 {service}: The submitted request is inconsistent with the current state of the Workitem."
)
UPS_WARNING_MISSING_TRANSACTION_UID = "Warning: 299 {service}: The Transaction UID is missing."
UPS_WARNING_INCORRECT_TRANSACTION_UID = "Warning: 299 {service}: The Transaction UID is incorrect."
UPS_WARNING_INCONSISTENT_WITH_UPS = (
    "Warning: 299 {service}: The submitted request is inconsistent with the state of the UPS Instance."
)

UPS_WARNING_STATE_IS_ALREADY_COMPLETED = "Warning: 299 {service}: The UPS is already in the requested state of COMPLETED."
UPS_WARNING_STATE_IS_ALREADY_CANCELED = "Warning: 299 {service}: The UPS is already in the requested state of CANCELED."


def get_base_uri(req: falcon.Request):
    # Extract scheme (http or https)
    scheme = req.scheme
    print(f"Scheme: {scheme}")
    # Get host (includes domain and potentially port)
    host = req.host
    print(f"Host: {host}")
    port = req.port
    print(f"Port: {port}")
    path = req.path
    print(f"Path: {path}")
    root_path = req.root_path
    print(f"Root Path: {root_path}")
    # Get the prefix part of the path (this depends on how your WSGI server is configured)
    # If you're using a reverse proxy or your app is mounted at a specific path
    prefix = req.prefix if hasattr(req, 'prefix') else ''
    print(f"Prefix: {prefix}")
    # If prefix starts with http:// or https://, extract only the path portion
    if prefix and (prefix.startswith('http://') or prefix.startswith('https://')):
        return prefix

    # Construct the base URI, not sure what the app path is.
    return f"{scheme}://{host}:{port}/{root_path}"


def serialise_list_of_ds_to_json(dataset_list: list[Dataset]) -> str:
    list_of_json_ds = [ds.to_json() for ds in dataset_list]
    return "[" + ','.join(list_of_json_ds) + "]"


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

    async def deserialize_async(self, stream: BoundedStream, content_type: str, content_length: int) -> dict[str, Any]:
        """
        Deserialize the request body from application/dicom+json.

        Args:
            stream: The request body stream.
            content_type: The content type of the request.
            content_length: The length of the request body.

        Returns:
            The parsed request body.

        """
        return self.deserialize()

    async def serialize_async(self, media: dict[str, Any], content_type: str) -> bytes:
        """
        Serialize the media object to application/dicom+json.

        Args:
            media: The media object to serialize.
            content_type: The content type to serialize to.

        Returns:
            The serialized media.

        """
        return self.serialize(media, content_type)


class WorkItemsResource(LoggerMixin):
    """Resource for handling collections of UPS workitems."""

    def __init__(self, workitem_service: svc_workitem_service = None) -> None:
        """
        Initialize the resource.

        Args:
            workitem_service: Service for handling workitem operations.

        """
        self.workitem_service = workitem_service
        if not self.workitem_service:
            workitem_crud = workitem_repository.WorkItemRepository(database_uri=Config.database_uri)
            self.workitem_service = svc_workitem_service.WorkItemService(
                workitem_repository=workitem_crud, notification_service=None
            )

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """
        Handle GET requests to retrieve a collection of workitems.

        Args:
            req: The HTTP request.
            resp: The HTTP response.

        """
        if workitem_uid := req.get_param("workitem"):
            # Retrieve workitem transaction.  Might need to return just the one item rather than a list of one item
            workitem_list = [self.workitem_service.workitem_repository.get_by_uid(workitem_uid)]
        else:
            params = dict(req.params)
            # match = req.get_param("match")
            non_match_param_list = ["includefield", "fuzzymatching", "offset", "limit"]
            include_field = req.get_param("includefield")
            fuzzy_matching = req.get_param("fuzzymatching")
            offset = req.get_param_as_int("offset")
            limit = req.get_param_as_int("limit")
            # strip out anything that we know is not a tag or keyword
            for non_match_param in non_match_param_list:
                if non_match_param in params:
                    del params[non_match_param]

            # what's left is a list of matching parameters, either as keywords or as hex values
            query_ds = Dataset()
            for key, value in params.items():
                try:
                    tag = int(key, base=16)

                    query_ds.add(DataElement(tag=tag,
                                             VR=datadict.dictionary_VR(tag),
                                             value=value))
                except ValueError:
                    try:
                        keyword = key
                        query_ds.add(DataElement(tag=keyword,
                                                 VR=datadict.dictionary_VR(keyword),
                                                 value=value))
                    except ValueError:
                        self.logger.error(f"Matching element had invalid tag or keyword: {key}")

            workitem_list = self.workitem_service.workitem_repository.get_filtered(match=query_ds,
                                                                                   include_field=include_field,
                                                                                   fuzzy_matching=fuzzy_matching,
                                                                                   offset=offset,
                                                                                   limit=limit)

        resp.content_type = "application/dicom+json"
        if workitem_list and len(workitem_list) > 0 and workitem_list[0] is not None and workitem_list[0].ds is not None:
            dataset_list = [x.ds for x in workitem_list]
            resp.status = falcon.HTTP_200
            json_response_text = ""
            try:
                json_response_text = serialise_list_of_ds_to_json(dataset_list=dataset_list)
            except Exception as e:
                print(f"Failed to serialise result as json string: {e}")
                resp.status = falcon.HTTP_404

            resp.text = json_response_text

        else:
            resp.status = falcon.HTTP_404

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

            resp.content_type = "application/dicom+json"

            if self.workitem_service.workitem_repository.get_by_uid(workitem.uid):
                resp.status = falcon.HTTP_409
            else:
                self.workitem_service.create_workitem(workitem=workitem)
                workitem_response = {"00080018": {"Value": [workitem.ds.SOPInstanceUID], "vr": "UI"}}
                resp.status = falcon.HTTP_201
                resp_media = json.dumps(workitem_response)
                resp.text = resp_media

        except Exception as e:
            # Log the exception
            raise falcon.HTTPInternalServerError(title="Error processing request", description=str(e)) from e


class WorkItemResource(LoggerMixin):
    """Resource for handling individual UPS workitems."""

    def __init__(self, workitem_service: svc_workitem_service = None) -> None:
        """
        Initialize the resource.

        Args:
            workitem_service: Service for handling workitem operations.

        """
        self.workitem_service = workitem_service
        if not self.workitem_service:
            workitem_crud = workitem_repository.WorkItemRepository(database_uri=Config.database_uri)
            self.workitem_service = svc_workitem_service.WorkItemService(
                workitem_repository=workitem_crud, notification_service=None
            )

    async def on_get(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
        """
        Handle GET requests to retrieve a specific workitem.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.

        """
        if workitem_uid:
            workitem = self.workitem_service.workitem_repository.get_by_uid(workitem_uid)
        else:
            resp.status = falcon.HTTP_404

        resp.content_type = "application/dicom+json"
        if workitem is not None and workitem.ds is not None:
            resp.status = falcon.HTTP_200
            json_response_text = ""
            try:
                json_response_text = workitem.ds.to_json()
            except Exception as e:
                print(f"Failed to serialise result as json string: {e}")

            resp.text = json_response_text

        else:
            resp.status = falcon.HTTP_404

    async def on_put(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
        """
        Handle PUT requests to update a workitem.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.

        """
        transaction_uid = req.params.get("transaction-uid")
        resp.content_type = "application/json"
        resp.status = falcon.HTTP_500  # if we don't manage to reset it, it's a coding problem
        # Manually read and parse the request body
        body = await req.stream.read()
        if not body:
            raise falcon.HTTPBadRequest(title="Empty request body", description="A valid DICOM JSON dataset is required")

        # Parse the JSON body
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise falcon.HTTPBadRequest(title="Invalid JSON", description="Request body must be valid JSON") from e

        workitem_update = deserialize_workitem(data)

        # Extract Procedure Step State (0074,1000)
        if hasattr(workitem_update.ds, "ProcedureStepState"):
            resp.append_header("Warning", UPS_WARNING_MODIFICATIONS.format(service=get_base_uri(req=req)))
            del workitem_update.ds["ProcedureStepState"]

        workitem = self.workitem_service.workitem_repository.get_by_uid(workitem_uid)
        if not workitem:
            resp.status = falcon.HTTP_404
            resp.append_header("Warning", UPS_WARNING_URI_UNCLAIMED_WORKITEM.format(service=get_base_uri(req=req)))
            return

        if transaction_uid:
            self.logger.info(f"Received Transaction UID {transaction_uid} as a parameter, this is an update transaction")
            if workitem.status != WorkItemStatus.SCHEDULED and workitem.transaction_uid != transaction_uid:
                resp.status = falcon.HTTP_400
                resp.append_header("Warning", UPS_WARNING_INCONSISTENT_WITH_STATE.format(service=get_base_uri(req=req)))  # The required message per 11.6.3.2
                resp.append_header(
                    "Warning", UPS_WARNING_MISSING_TRANSACTION_UID.format(service=get_base_uri(req=req))
                )  # A more accurate message that also fulfills 11.7.3.2
            else:
                resp.status = falcon.HTTP_200
        elif workitem.status == WorkItemStatus.SCHEDULED:
            resp.status = falcon.HTTP_200
        else:
            resp.status = falcon.HTTP_400

            resp.append_header("Warning", UPS_WARNING_INCONSISTENT_WITH_STATE.format(service=get_base_uri(req=req)))  # The required message per 11.6.3.2
            resp.append_header("Warning", UPS_WARNING_MISSING_TRANSACTION_UID.format(service=get_base_uri(req=req)))  # A more accurate message fulfilling 11.7.3.2

        if resp.status == falcon.HTTP_200:
            workitem_update.uid = workitem_uid
            workitem.updated_at = datetime.now()
            # store the update, i.e. persist it in the database
            self.workitem_service.workitem_repository.update(workitem_update)
        if resp.status == falcon.HTTP_500:
            self.logger.error("Internal UPS logic error, corner case not addressed?")
            self.logger.error(f"UID {workitem} and Transaction UID {transaction_uid} had Message body : {body}")

    async def on_post(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
        """
        Handle POST requests to cancel a workitem.

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
            cancel_workitem = deserialize_workitem(json_dicom)
            cancel_workitem.uid = workitem_uid
            cancel_workitem.ds.SOPInstanceUID = cancel_workitem.uid
            resp.content_type = "application/dicom+json"

            canceled: bool = False

            stored_workitem = self.workitem_service.workitem_repository.get_by_uid(workitem_uid)
            if stored_workitem is None:
                resp.status = falcon.HTTP_404
            else:
                # Try to cancel it
                _, canceled = self.workitem_service.update_workitem_status(workitem_uid,
                                                                           new_status=WorkItemStatus.CANCELED,
                                                                           transaction_uid=None)
                if canceled:
                    # update to include whatever reasons and notification information
                    # TODO: check within update to see if the update contains cancellation request information and
                    # trigger a notification (although that notification will be a stub... this is an example, not
                    # intended to be commercial grade)
                    self.workitem_service.workitem_repository.update(cancel_workitem)

                resp.status = falcon.HTTP_202 if canceled else falcon.HTTP_409
                        # resp_media = json.dumps(workitem_response)
                        # resp.text = resp_media

        except Exception as e:
            # Log the exception
            raise falcon.HTTPInternalServerError(title="Error processing request", description=str(e)) from e


class WorkItemStateResource(LoggerMixin):
    """Resource for handling individual UPS workitems."""

    def __init__(self, workitem_service: svc_workitem_service = None) -> None:
        """
        Initialize the resource.

        Args:
            workitem_service: Service for handling workitem operations.

        """
        self.workitem_service = workitem_service
        if not self.workitem_service:
            workitem_crud = workitem_repository.WorkItemRepository(database_uri=Config.database_uri)
            self.workitem_service = svc_workitem_service.WorkItemService(
                workitem_repository=workitem_crud, notification_service=None
            )

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
        new_state: WorkItemStatus = WorkItemStatus.IN_PROGRESS
        # Manually read and parse the request body
        body = await req.stream.read()
        if not body:
            raise falcon.HTTPBadRequest(title="Empty request body", description="A valid DICOM JSON dataset is required")

        # Parse the JSON body
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise falcon.HTTPBadRequest(title="Invalid JSON", description="Request body must be valid JSON") from e

        change_state_request = data

        # Extract Procedure Step State (0074,1000)
        procedure_step_state = None
        transaction_uid = None

        if isinstance(change_state_request, dict):
            # Extract Procedure Step State (0074,1000)
            if "00741000" in change_state_request and "Value" in change_state_request["00741000"]:
                procedure_step_state = change_state_request["00741000"]["Value"][0]

            # Extract Transaction UID (0008,1195)
            if "00081195" in change_state_request and "Value" in change_state_request["00081195"]:
                transaction_uid = change_state_request["00081195"]["Value"][0]

        if not procedure_step_state and not transaction_uid:
            # This is probably an update transaction that didn't have a transaction UID
            resp.status = falcon.HTTP_400
            resp.content_type = "application/json"
            # TODO: refactor to extract warning message strings as constants.
            msg = "Warning: 299 {service}: The submitted request is inconsistent with the current state of the Workitem."
            full_msg = "Warning: 299 {service}: The Transaction UID is missing."
            resp.append_header("Warning", msg.format(service=get_base_uri(req=req)))  # The required message per 11.6.3.2
            resp.append_header("Warning", full_msg.format(service=get_base_uri(req=req)))  # A more accurate message that also fulfills 11.7.3.2 if state transaction
            return

        new_state = WorkItemStatus.from_string(procedure_step_state)  # throws an exception if procedure_step_state not valid
        workitem = self.workitem_service.workitem_repository.get_by_uid(workitem_uid)
        if workitem is None:
            resp.status = falcon.HTTP_404
            self.logger.error(f"No workitem found for {workitem_uid}")
        elif workitem.status in [WorkItemStatus.COMPLETED, WorkItemStatus.CANCELED]:
            if new_state == workitem.status:
                resp.status = falcon.HTTP_410
                msg = f"Warning: 299 {get_base_uri(req=req)}: The UPS is already in the requested state of {workitem.status.value}."
                self.logger.error(msg)
            else:
                resp.status = falcon.HTTP_409
                msg = f"Warning: 299 {get_base_uri(req=req)}: The submitted request is inconsistent with the state of the UPS Instance."
                self.logger.error(msg)

            resp.append_header("Warning", msg)
        elif workitem.status in [WorkItemStatus.IN_PROGRESS] and new_state not in [
            WorkItemStatus.COMPLETED,
            WorkItemStatus.CANCELED,
        ]:
            resp.status = falcon.HTTP_409
            msg = "Warning: 299 {service}: The submitted request is inconsistent with the state of the UPS Instance."
            self.logger.error(msg)
            resp.append_header("Warning", msg.format(service=get_base_uri(req=req)))
        elif not transaction_uid:
            resp.status = falcon.HTTP_400
            msg = "Warning: 299 {service}: The Transaction UID is missing."
            self.logger.error(msg)
            resp.append_header("Warning", msg.format(service=get_base_uri(req=req)))
        elif new_state != WorkItemStatus.IN_PROGRESS and transaction_uid != workitem.transaction_uid:
            resp.status = falcon.HTTP_400
            msg = "Warning: 299 {service}: The Transaction UID is incorrect."
            self.logger.error(msg)
            resp.append_header("Warning", msg.format(service=get_base_uri(req=req)))
        else:
            workitem, update_succeeded = self.workitem_service.update_workitem_status(
                workitem_uid, new_status=new_state, transaction_uid=transaction_uid
            )
            resp.status = falcon.HTTP_200 if update_succeeded else falcon.HTTP_400

        resp.content_type = "application/json"
