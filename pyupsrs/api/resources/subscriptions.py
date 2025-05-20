"""Falcon resources for UPS subscriptions."""

from urllib.parse import urlparse

import falcon
from pydicom import DataElement, Dataset, datadict

from pyupsrs.config import Config
from pyupsrs.domain.models.ups import FILTERED_SUBSCRIPTION_UID, GLOBAL_SUBSCRIPTION_UID, Subscription
from pyupsrs.domain.services import subscription_service as svc_subscription_service
from pyupsrs.storage.repositories import subscription_repository
from pyupsrs.utils.class_logger import LoggerMixin


class SubscriptionSuspendResource(LoggerMixin):
    """Resource for handling collections of UPS subscriptions."""

    def __init__(self, subscription_service: svc_subscription_service = None) -> None:
        """
        Initialize the resource.

        Args:
            subscription_service: Service for handling workitem operations.

        """
        self.subscription_service = subscription_service
        if not self.subscription_service:
            subscription_crud = subscription_repository.SubscriptionRepository(database_uri=Config.database_uri)
            self.subscription_service = svc_subscription_service.SubscriptionService(subscription_repository=subscription_crud)

    async def on_get(self, req: falcon.Request, resp: falcon.Response, aetitle: str) -> None:
        """
        Handle GET requests to retrieve a collection of subscriptions.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            aetitle: The AE Title of the subscriber.

        """
        # TODO: Implement subscription query
        resp.media = {"subscriptions": []}
        resp.content_type = "application/dicom+json"
        resp.status = falcon.HTTP_200
        self.logger.error("Subscription Suspension on_get is only stubbed")

    async def on_post(self, req: falcon.Request, resp: falcon.Response, aetitle: str) -> None:
        """
        Handle POST requests to suspend the subscription.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            aetitle: The AE Title of the suspend requestor.

        """
        resp.status = falcon.HTTP_200
        resp.content_type = "application/dicom+json"
        path = req.path
        workitem_uid = None
        if GLOBAL_SUBSCRIPTION_UID in path:
            workitem_uid = GLOBAL_SUBSCRIPTION_UID
        elif FILTERED_SUBSCRIPTION_UID in path:
            workitem_uid = FILTERED_SUBSCRIPTION_UID
        self.logger.info(f"Attempting to suspend subscription for {aetitle} to {workitem_uid}")
        suspended = self.subscription_service.suspend(workitem_uid=workitem_uid, ae_title=aetitle)

        if not suspended:
            resp.status = falcon.HTTP_404
        else:
            self.logger.debug(f"Suspended: {suspended}")


class SubscriptionResource(LoggerMixin):
    """Resource for handling individual UPS subscriptions."""

    def __init__(self, subscription_service: svc_subscription_service = None) -> None:
        """
        Initialize the resource.

        Args:
            subscription_service: Service for handling workitem operations.

        """
        self.subscription_service = subscription_service
        if not self.subscription_service:
            subscription_crud = subscription_repository.SubscriptionRepository(database_uri=Config.database_uri)
            self.subscription_service = svc_subscription_service.SubscriptionService(subscription_repository=subscription_crud)

    def _extract_hostname(self, host_string: str) -> str:
        """
        Safely extract the hostname from a string that might contain port information.

        This function properly handles IPv4 addresses, IPv6 addresses, and domain names.

        Args:
            host_string: A string containing a hostname and possibly port information

        Returns:
            The hostname without port information

        """
        # Handle IPv6 addresses (which contain colons)
        if host_string.startswith("[") and "]" in host_string:
            return host_string[: host_string.find("]") + 1]  # preserve brackets, it's an IPV6 address.
        # For normal hostnames and IPv4 addresses
        # Use urlparse which properly handles hostnames with ports
        parsed = urlparse(f"//{host_string}")
        return parsed.hostname or host_string

    # def _add_websocket_url_header(self, req: falcon.Request, resp: falcon.Response, aetitle: str) -> None:
    #     """
    #     Add WebSocket connection URL to response headers.

    #     Args:
    #         req: The request object.
    #         resp: The response object.
    #         aetitle: The AE title of the subscriber.

    #     """
    #     # Get the base URI components
    #     if req.url.startswith("https"):
    #         ws_protocol = "wss"
    #     else:
    #         ws_protocol = "ws"
    #         self.logger.warning(f"Using ws protocol for {req.url}")

    #     req.uri
    #     client_facing_host_and_port = req.url.netloc
    #     ws_url = f"{ws_protocol}://{client_facing_host_and_port}/ws/subscribers/{aetitle}"
    #     self.logger.info(f"WebSocket URL: {ws_url}")
    #     resp.set_header("Content-Location", ws_url)
    #     return

    def _add_websocket_url_header(self, req: falcon.Request, resp: falcon.Response, aetitle: str) -> None:
        """
        Add WebSocket connection URL to response headers that works through Nginx proxy.

        Args:
            req: The request object.
            resp: The response object.
            aetitle: The AE title of the subscriber.

        """
        # Extract the original client-facing scheme, host and port
        scheme, host, port = self._extract_original_request_info(req)

        self.logger.warning("All headers received:")
        for key in req.headers.keys():
            self.logger.warning(f"  {key} => {req.headers[key]}")
        # Get any path prefix from X-Forwarded-Prefix header
        prefix = (
            req.headers.get("X-Forwarded-Prefix")
            or req.headers.get("x-forwarded-prefix")
            or req.headers.get("X-FORWARDED-PREFIX")
            or req.prefix
            or ""
        )
        if prefix:
            self.logger.warning(f"WebSocket URL prefix is {prefix}")
        else:
            self.logger.warning("No WebSocket URL prefix")

        # Switch protocol from http/https to ws/wss
        ws_protocol = "wss" if scheme == "https" else "ws"

        # Construct the WebSocket URL - note that we don't include the port if it's standard
        if (ws_protocol == "ws" and port == 80) or (ws_protocol == "wss" and port == 443):
            ws_url = f"{ws_protocol}://{host}{prefix}/ws/subscribers/{aetitle}"
        else:
            ws_url = f"{ws_protocol}://{host}:{port}{prefix}/ws/subscribers/{aetitle}"

        # Log the generated WebSocket URL for debugging
        self.logger.warning(f"WebSocket URL converted to {ws_url}")
        resp.set_header("Content-Location", ws_url)

    def _extract_original_request_info(self, req: falcon.Request) -> tuple[str, str, int]:
        """
        Extract the original client-facing scheme, host, and port from a proxied request.

        Args:
            req: The Falcon Request object.

        Returns:
            Tuple containing (scheme, host, port)

        """
        # Get scheme - prefer X-Forwarded-Proto if available
        scheme = req.headers.get("X-Forwarded-Proto", req.scheme)

        # Get host - prefer X-Forwarded-Host if available
        forwarded_host = req.headers.get("X-Forwarded-Host")
        host_with_port = forwarded_host or req.host
        # Extract host and port
        if ":" in host_with_port:
            host, port_str = host_with_port.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                # Default ports if conversion fails
                port = 443 if scheme == "https" else 80
        else:
            host = host_with_port
            if forwarded_port := req.headers.get("X-Forwarded-Port"):
                try:
                    port = int(forwarded_port)
                except ValueError:
                    # Default ports if conversion fails
                    port = 443 if scheme == "https" else 80
            else:
                # Use the standard ports if no specific port information
                port = 443 if scheme == "https" else 80

        return scheme, host, port

    async def on_delete(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str, aetitle: str) -> None:
        """
        Handle DELETE requests to unsubscribe.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.
            aetitle: The AE Title of the subscriber.

        """
        resp.status = falcon.HTTP_200
        deleted = self.subscription_service.delete_subscription(workitem_uid=workitem_uid, ae_title=aetitle)
        if not deleted:
            resp.status = falcon.HTTP_404

    async def on_post(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str, aetitle: str) -> None:
        """
        Handle POST requests to create a new subscription.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.
            aetitle: The AE Title of the subscriber.

        """
        resp.status = falcon.HTTP_201
        resp.content_type = "application/dicom+json"
        deletion_lock = req.get_param_as_bool("deletionlock")
        self.logger.warning(f"path = {req.path}")
        subscription_filter = None

        params = dict(req.params)
        self.logger.warning(f"Subscription Params: {params}")
        if "deletionlock" in params:
            del params["deletionlock"]
        if "filter" in params:
            filter_paired_strings = params["filter"].split(",")
            filter_element_dict = {}
            for filter_element in filter_paired_strings:
                key, value = filter_element.split("=")
                filter_element_dict[key] = value

            # what's left is a list of matching parameters, either as keywords or as hex values
            query_ds = Dataset()
            for key, value in filter_element_dict.items():
                self.logger.warning(f"Filtering element: {key} = {value}")
                try:
                    tag = int(key, base=16)

                    query_ds.add(DataElement(tag=tag, VR=datadict.dictionary_VR(tag), value=value))
                except ValueError:
                    try:
                        keyword = key
                        query_ds.add(DataElement(tag=keyword, VR=datadict.dictionary_VR(keyword), value=value))
                    except ValueError:
                        self.logger.error(f"Filtering element had invalid tag or keyword: {key}")

            subscription_filter = query_ds
            self.logger.warning(f"Subscription Filter: {subscription_filter}")

        if not workitem_uid:
            if subscription_filter:
                workitem_uid = FILTERED_SUBSCRIPTION_UID
            else:
                workitem_uid = GLOBAL_SUBSCRIPTION_UID

        subscription = Subscription(
            workitem_uid=workitem_uid, ae_title=aetitle, deletion_lock=deletion_lock, filter=subscription_filter
        )
        self.logger.warning(f"Subscription: {subscription}")
        self.subscription_service.create_subscription(subscription)

        # Add WebSocket URL to response header
        self._add_websocket_url_header(req, resp, aetitle)
