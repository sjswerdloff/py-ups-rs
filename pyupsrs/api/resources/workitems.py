"""Falcon resources for UPS workitems."""

import falcon


class WorkItemsResource:
    """Resource for handling collections of UPS workitems."""

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
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

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """
        Handle POST requests to create a new workitem.

        Args:
            req: The HTTP request.
            resp: The HTTP response.

        """
        # TODO: Implement workitem creation
        resp.status = falcon.HTTP_201
        resp.content_type = "application/dicom+json"


class WorkItemResource:
    """Resource for handling individual UPS workitems."""

    def on_get(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
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

    def on_put(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
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
