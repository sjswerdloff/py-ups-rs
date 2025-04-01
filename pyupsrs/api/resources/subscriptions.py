"""Falcon resources for UPS subscriptions."""

import falcon


class SubscriptionsResource:
    """Resource for handling collections of UPS subscriptions."""

    async def on_get(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
        """
        Handle GET requests to retrieve a collection of subscriptions.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.

        """
        # TODO: Implement subscription query
        resp.media = {"subscriptions": []}
        resp.content_type = "application/dicom+json"
        resp.status = falcon.HTTP_200

    async def on_post(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str) -> None:
        """
        Handle POST requests to create a new subscription.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.

        """
        # TODO: Implement subscription creation
        resp.status = falcon.HTTP_201
        resp.content_type = "application/dicom+json"


class SubscriptionResource:
    """Resource for handling individual UPS subscriptions."""

    async def on_delete(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str, subscriber_uid: str) -> None:
        """
        Handle DELETE requests to unsubscribe.

        Args:
            req: The HTTP request.
            resp: The HTTP response.
            workitem_uid: The UID of the workitem.
            subscriber_uid: The UID of the subscriber.

        """
        # TODO: Implement subscription deletion
        resp.status = falcon.HTTP_200
