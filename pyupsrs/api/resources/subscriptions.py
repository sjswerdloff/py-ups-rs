"""Falcon resources for UPS subscriptions."""

import falcon
from pyupsrs.utils.class_logger import LoggerMixin


class SubscriptionSuspendResource(LoggerMixin):
    """Resource for handling collections of UPS subscriptions."""

    async def on_get(self, req: falcon.Request, resp: falcon.Response, aetitle: str) -> None:
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
        self.logger.error("Subscription Suspension on_get is only stubbed")

    async def on_post(self, req: falcon.Request, resp: falcon.Response, aetitle: str) -> None:
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
        self.logger.error("Subscription Suspension on_post is only stubbed")


class SubscriptionResource(LoggerMixin):
    """Resource for handling individual UPS subscriptions."""

    async def on_delete(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str, aetitle: str) -> None:
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
        self.logger.error("Subscription on_delete is only stubbed")

    async def on_post(self, req: falcon.Request, resp: falcon.Response, workitem_uid: str, aetitle: str) -> None:
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
        self.logger.error("Subscription on_post is only stubbed")
