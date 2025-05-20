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
        # Extract all request information in one central place
        scheme, host, port, path_prefix, websocket_scheme = self._extract_original_request_info(req)

        # Log information about WebSocket URL generation
        if path_prefix:
            self.logger.info(f"WebSocket URL prefix is {path_prefix}")
        else:
            self.logger.info("No WebSocket URL prefix")

        # Construct the WebSocket URL - include port unless it's standard
        standard_port = (websocket_scheme == "ws" and port == 80) or (websocket_scheme == "wss" and port == 443)

        if standard_port:
            ws_url = f"{websocket_scheme}://{host}{path_prefix}/ws/subscribers/{aetitle}"
        else:
            ws_url = f"{websocket_scheme}://{host}:{port}{path_prefix}/ws/subscribers/{aetitle}"

        self.logger.info(f"WebSocket URL converted to {ws_url}")

        # Set the header and log for debugging
        resp.set_header("content-location", ws_url)

        self.logger.debug("Headers being set in response:")
        for name, value in resp.headers.items():
            self.logger.debug(f"  {name}: {value}")

    def _extract_original_request_info(self, req: falcon.Request) -> tuple[str, str, int, str, str]:
        """
        Extract comprehensive client-facing request information from a proxied request.

        When receiving a request through a reverse proxy (like Nginx), the original client
        request information (scheme, host, port) is typically stored in X-Forwarded-* headers.
        This method extracts this information to reconstruct the original client-facing URLs,
        which is essential for generating correct WebSocket connection URLs.

        The method prioritizes information in the following order:
        1. X-Forwarded-* headers (for proxied requests)
        2. Request object's native properties (for direct requests)
        3. Sensible defaults based on the scheme

        Args:
            req: The Falcon Request object containing HTTP headers and request information.
                Expected headers include X-Forwarded-Proto, X-Forwarded-Host, X-Forwarded-Port,
                X-Forwarded-Prefix, and X-Websocket-Scheme.

        Returns:
            A tuple containing five elements:
            - scheme (str): The HTTP scheme used by the client ('http' or 'https')
            - host (str): The hostname used by the client (e.g., 'localhost', 'example.com')
            - port (int): The port number used by the client (e.g., 80, 443, 9080)
            - path_prefix (str): Any path prefix from X-Forwarded-Prefix (e.g., '/dicom-web')
            - websocket_scheme (str): The WebSocket scheme to use ('ws' or 'wss')

        Notes:
            - The method uses case-insensitive header lookups via Falcon's get_header method
            - If X-Forwarded-Port is missing or invalid, it falls back to standard ports (80/443)
            - If X-Websocket-Scheme is missing, it derives it from the HTTP scheme
            (http → ws, https → wss)

        Example:
            When a client connects to https://example.com:9443/dicom-web/..., the method
            would typically return:
            ('https', 'example.com', 9443, '/dicom-web', 'wss')

        """
        # Case-insensitive header lookups using Falcon's built-in method
        scheme = req.get_header("X-Forwarded-Proto", default=req.scheme)
        websocket_scheme = req.get_header("X-Websocket-Scheme") or ("wss" if scheme == "https" else "ws")

        forwarded_host = req.get_header("X-Forwarded-Host")
        host_with_port = forwarded_host or req.host

        # Extract host and port
        if ":" in host_with_port:
            host, port_str = host_with_port.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 443 if scheme == "https" else 80
        else:
            host = host_with_port
            if forwarded_port := req.get_header("X-Forwarded-Port"):
                try:
                    port = int(forwarded_port)
                except ValueError:
                    port = 443 if scheme == "https" else 80
            else:
                port = 443 if scheme == "https" else 80

        path_prefix = req.get_header("X-Forwarded-Prefix", default="")

        return scheme, host, port, path_prefix, websocket_scheme

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
