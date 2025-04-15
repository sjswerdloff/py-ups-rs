"""Falcon resources for UPS subscriptions."""

import falcon
from pydicom import datadict, DataElement, Dataset
from pyupsrs.config import Config
from pyupsrs.domain.models.ups import Subscription, GLOBAL_SUBSCRIPTION_UID, FILTERED_SUBSCRIPTION_UID
from pyupsrs.storage.repositories import subscription_repository
from pyupsrs.utils.class_logger import LoggerMixin
from pyupsrs.domain.services import subscription_service as svc_subscription_service

class SubscriptionSuspendResource(LoggerMixin):
    """Resource for handling collections of UPS subscriptions."""

    def __init__(self, subscription_service: svc_subscription_service = None) -> None:
        """
        Initialize the resource.

        Args:
            workitem_service: Service for handling workitem operations.

        """
        self.subscription_service = subscription_service
        if not self.subscription_service:
            subscription_crud = subscription_repository.SubscriptionRepository(database_uri=Config.database_uri)
            self.subscription_service = svc_subscription_service.SubscriptionService(
                subscription_repository=subscription_crud
            )

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
        path = req.path
        workitem_uid = None
        if GLOBAL_SUBSCRIPTION_UID in path:
            workitem_uid = GLOBAL_SUBSCRIPTION_UID
        elif FILTERED_SUBSCRIPTION_UID in path:
            workitem_uid = FILTERED_SUBSCRIPTION_UID
        suspended = self.subscription_service.suspend(workitem_uid=workitem_uid, ae_title=aetitle)
        if not suspended:
            resp.status = falcon.HTTP_404


class SubscriptionResource(LoggerMixin):
    """Resource for handling individual UPS subscriptions."""

    def __init__(self, subscription_service: svc_subscription_service = None) -> None:
            """
            Initialize the resource.

            Args:
                workitem_service: Service for handling workitem operations.

            """
            self.subscription_service = subscription_service
            if not self.subscription_service:
                subscription_crud = subscription_repository.SubscriptionRepository(database_uri=Config.database_uri)
                self.subscription_service = svc_subscription_service.SubscriptionService(
                    subscription_repository=subscription_crud
                )

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
        deleted = self.subscription_service.delete_subscription(workitem_uid=workitem_uid,ae_title=aetitle)
        if not deleted:
            resp.status = falcon.HTTP_404

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
        deletion_lock = req.get_param_as_bool("deletionlock")

        subscription_filter = None

        params = dict(req.params)
        if "deletionlock" in params:
            del params["deletionlock"]
        if params:
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
                        self.logger.error(f"Filtering element had invalid tag or keyword: {key}")
            subscription_filter = query_ds

        subscription = Subscription(workitem_uid=workitem_uid,
                                    ae_title=aetitle,
                                    deletion_lock=deletion_lock,
                                    filter=subscription_filter)
        self.subscription_service.create_subscription(subscription)
