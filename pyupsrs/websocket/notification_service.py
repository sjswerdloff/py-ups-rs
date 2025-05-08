"""WebSocket notification service for UPS events."""

import asyncio
from copy import deepcopy
from enum import Enum, StrEnum
from functools import lru_cache
from typing import Any

from pydicom import DataElement, Dataset, Sequence

import pyupsrs.domain.services.service_provider as service_provider  # avoid circular reference to ServiceProvider singleton
from pyupsrs.domain.models.ups import FILTERED_SUBSCRIPTION_UID, GLOBAL_SUBSCRIPTION_UID, Subscription, WorkItem
from pyupsrs.utils.class_logger import LoggerMixin
from pyupsrs.utils.dicom_query_matcher import match_query_to_dataset
from pyupsrs.websocket.connection_manager import ConnectionManager

_message_id: int = 1


def get_next_message_id() -> int:
    """
    Increments message id to enforce monotonicity.

    Returns:
        int: the message ID for use in communication with other AEs

    """
    global _message_id
    if _message_id > 65534:
        _message_id = 1
    else:
        _message_id += 1
    return _message_id


@lru_cache
def _workitem_event_report_template() -> Dataset:
    ds = Dataset()
    ds.AffectedSOPClassUID = "1.2.840.10008.5.1.4.34.6.4"
    ds.MessageID = 1
    ds.AffectedSOPInstanceUID = None
    ds.EventTypeID = 0
    ds.InputReadinessState = "READY"
    ds.ProcedureStepState = "SCHEDULED"

    return ds


class UPSEventType(Enum):
    """Enumerates UPS Event Types."""

    UPSStateReport = 1
    UPSCancelRequested = 2
    UPSProgressReport = 3
    SCPStatusChange = 4
    UPSAssigned = 5


class SCPStatus(StrEnum):
    """Enumerates SCP Status."""

    RESTARTED = "RESTARTED"
    GOING_DOWN = "GOING DOWN"


class ListRestartStatus(StrEnum):
    """Enumerates Subscription List and UPS List Restart Status."""

    WARM_START = "WARM START"
    COLD_START = "COLD START"


_PROCEDURE_STEP_STATES = {
    "SCHEDULED": "SCHEDULED",
    "IN PROGRESS": "IN PROGRESS",
    "COMPLETED": "COMPLETED",
    "CANCELED": "CANCELED",
}


def _create_workitem_event_report(
    affected_sop_instance_uid: str,
    event_type_id: UPSEventType,
    input_readiness_state: str = "READY",
    procedure_step_state: str = "SCHEDULED",
    additional_dataset_info: Dataset | None = None,
) -> Dataset:
    """
    Create a Workitem Event Report.

    Acts as a base function for specific types of event reports.
    This should not be called directly outside of this module.


    Args:
        affected_sop_instance_uid (str): affected_sop_instance_uid
        event_type_id (UPSEventType): event_type_id
        input_readiness_state (str, optional): input_readiness_state. Defaults to "READY".
        procedure_step_state (str, optional): procedure_step_state. Defaults to "SCHEDULED".
        additional_dataset_info (Dataset | None, optional): additional_dataset_info provided by and for
        specific types of event reports. Defaults to None.

    Returns:
        Dataset: the UPS Event Report in pydicom.Dataset format (use .to_json() for DICOMWeb)

    """
    event_report = deepcopy(_workitem_event_report_template())
    event_report.AffectedSOPInstanceUID = affected_sop_instance_uid
    event_report.MessageID = get_next_message_id()
    event_report.EventTypeID = event_type_id.value
    event_report.InputReadinessState = input_readiness_state
    defined_state: str = _PROCEDURE_STEP_STATES.get(procedure_step_state, "SCHEDULED")  # might be better to raise an error?
    event_report.ProcedureStepState = defined_state
    if additional_dataset_info:
        event_report.update(additional_dataset_info)
    return event_report


def create_ups_state_report(
    affected_sop_instance_uid: str,
    procedure_step_state: str,
    input_readiness_state: str,
    reason_for_cancellation: str | None = None,
) -> Dataset:
    """
    Create a UPS State Report (Event Report).

    Args:
        affected_sop_instance_uid (str): affected_sop_instance_uid
        procedure_step_state (str): procedure_step_state
        input_readiness_state (str): input_readiness_state
        reason_for_cancellation (str | None, optional): reason_for_cancellation. Defaults to None.

    Returns:
        Dataset: the UPS State Report in pydicom.Dataset format (use .to_json() for DICOMWeb)

    """
    additional_dataset_info = None
    if reason_for_cancellation:
        additional_dataset_info = Dataset()
        additional_dataset_info["ReasonForCancellation"] = reason_for_cancellation

    return _create_workitem_event_report(
        affected_sop_instance_uid,
        UPSEventType.UPSStateReport,
        input_readiness_state=input_readiness_state,
        procedure_step_state=procedure_step_state,
        additional_dataset_info=additional_dataset_info,
    )


def create_ups_cancel_requested_report(
    affected_sop_instance_uid: str,
    procedure_step_state: str,
    input_readiness_state: str,
    requesting_ae: str,
    reason_for_cancellation: str | None = None,
    contact_uri: str | None = None,
    contact_display_name: str | None = None,
) -> Dataset:
    """
    Create a UPS Cancel Requested Event Report.

    A requested cancellation doesn't mean that it necessarily *is* or *was* cancelled.
    In theory, the request might get put in to a queue (outside the scope of UPS-RS) that requires approval or rejection.
    That information (outside the scope of UPS-RS) then flows to the system that can actually directly cancel the UPS.

    Args:
        affected_sop_instance_uid (str): The (Affected) SOP Instance UID of the workitem, i.e. the "workitem_uid"
        procedure_step_state (str): procedure_step_state
        input_readiness_state (str): input_readiness_state
        requesting_ae (str): The AE that requested the cancellation
        reason_for_cancellation (str | None, optional): reason_for_cancellation. Defaults to None.
        contact_uri (str | None, optional): contact_uri (like mailto:frontdesk.oncology@bighospital.org or sms:+19725551212 ).
            Defaults to None.
        contact_display_name (str | None, optional): The name to show for who to contact regarding the requested cancellation.
            Defaults to None.

    Returns:
        Dataset: the UPS Cancel Requested Event Report

    """
    additional_dataset_info = Dataset()
    additional_dataset_info["RequestingAE"] = requesting_ae
    if reason_for_cancellation:
        additional_dataset_info["ReasonForCancellation"] = reason_for_cancellation
    if contact_uri:
        additional_dataset_info["ContactURI"] = contact_uri
    if contact_display_name:
        additional_dataset_info["ContactDisplayName"] = contact_display_name
    return _create_workitem_event_report(
        affected_sop_instance_uid,
        UPSEventType.UPSCancelRequested,
        input_readiness_state=input_readiness_state,
        procedure_step_state=procedure_step_state,
        additional_dataset_info=additional_dataset_info,
    )


def create_ups_progress_report(
    affected_sop_instance_uid: str,
    procedure_step_state: str,
    input_readiness_state: str,
    procedure_step_progress: int,
    progress_description: str | None = None,
    contact_uri: str | None = None,
    contact_display_name: str | None = None,
) -> Dataset:
    """
    Create a UPS Progress Report.

    Args:
        affected_sop_instance_uid (str): affected_sop_instance_uid
        procedure_step_state (str): procedure_step_state
        input_readiness_state (str): input_readiness_state
        procedure_step_progress (int): from 0 to 100 (percent)
        progress_description (str | None, optional): progress_description. Defaults to None.
        contact_uri (str | None, optional): contact_uri (like mailto:frontdesk.oncology@bighospital.org or sms:+19725551212 ).
            Defaults to None.
        contact_display_name (str | None, optional): The name to show for who to contact regarding the requested cancellation.
            Defaults to None.

    Returns:
        Dataset: The UPS Progress Report (as a pydicom.Dataset, use .to_json() for DICOMWeb)

    """
    additional_dataset_info = Dataset()
    procedure_step_progress_sequence = Sequence()
    info_sequence_item = Dataset()
    if procedure_step_progress >= 0 and procedure_step_progress <= 100:
        pass
    elif procedure_step_progress < 0:
        procedure_step_progress = 0
    else:
        procedure_step_progress = 100

    info_sequence_item["ProcedureStepProgress"] = procedure_step_progress
    info_sequence_item["ProcedureStepProgressDescription"] = progress_description

    procedure_step_communications_uri_sequence = Sequence()
    uri_sequence_item = Dataset()
    uri_sequence_item["ContactURI"] = contact_uri
    uri_sequence_item["ContactDisplayName"] = contact_display_name
    procedure_step_communications_uri_sequence.append(uri_sequence_item)
    info_sequence_item.ProcedureStepCommunicationsURISequence = procedure_step_communications_uri_sequence

    procedure_step_progress_sequence.append(info_sequence_item)
    additional_dataset_info.ProcedureStepProgressSequence = procedure_step_progress_sequence
    return _create_workitem_event_report(
        affected_sop_instance_uid,
        UPSEventType.UPSProgressReport,
        input_readiness_state=input_readiness_state,
        procedure_step_state=procedure_step_state,
        additional_dataset_info=additional_dataset_info,
    )


def create_scp_status_change_report(
    scp_status: SCPStatus, subscription_list_status: ListRestartStatus, ups_list_status: ListRestartStatus
) -> Dataset:
    """
    Creates an SCP Status Change Report.

    Unlike the other types of UPS Event Reports, this concerns the status of the AE maintaining
    the UPS List and the Subscription List, and is used to notify subscribers to UPS Events
    that the ship is going down (or coming back up).
    The key point for subscribers is that if they get told that the SCP is going down,
    but they don't get told it came back up (but then they reach it at some point),
    then they need to assume it was a cold start (and resubscribe, and any current workitems (UPS) might have been lost,
    so... "cleanup on aisle 3").
    See CC.2.4.3 Service Class Provider Behavior
    ( https://dicom.nema.org/medical/dicom/current/output/html/part04.html#table_CC.2-4 will get you close to that)

    Args:
        scp_status (SCPStatus): Whether the SCP is GOING DOWN or being RESTARTED
        subscription_list_status (ListRestartStatus): Whether the list has a WARM START
            (was stored to some extent and read back in)
            or COLD START (was only in memory and that is long gone)
        ups_list_status (ListRestartStatus): Whether the list has a WARM START (was stored to some extent and read back in)
            or COLD START (was only in memory and that is long gone)

    Returns:
        Dataset: The SCP Status Change Report

    """  # noqa: D401
    additional_dataset_info = Dataset()
    additional_dataset_info.SCPStatus = scp_status
    additional_dataset_info.SubscriptionListStatus = subscription_list_status
    additional_dataset_info.UnifiedProcedureStepListStatus = ups_list_status
    return _create_workitem_event_report("", UPSEventType.SCPStatusChange, additional_dataset_info=additional_dataset_info)


def create_ups_assigned_report(workitem_ds: Dataset) -> Dataset:
    """
    Create UPS Assigned Event Report.

    This is to notify global or filtered subscribers of a new UPS

    Args:
        workitem_ds (Dataset): The UPS represented as a pydicom.Dataset

    Returns:
        Dataset: The UPS Assigned Event Report

    """
    affected_sop_instance_uid = workitem_ds.get("AffectedSOPInstanceUID") or workitem_ds.get("SOPInstanceUID")
    procedure_step_state = "SCHEDULED"
    input_readiness_state = (
        workitem_ds.get("InputReadinessState") or "READY"
    )  # tough beans if it isn't ready and didn't say so
    additional_dataset_info = Dataset()
    scheduled_station_name_sequence = workitem_ds.get("ScheduledStationNameCodeSequence")
    human_performer_sequence = workitem_ds.get("HumanPerformerCodeSequence")
    human_performers_organization_sequence = workitem_ds.get("HumanPerformersOrganizationSequence")
    if scheduled_station_name_sequence:
        additional_dataset_info.ScheduledStationNameCodeSequence = scheduled_station_name_sequence
    if human_performer_sequence:
        additional_dataset_info.HumanPerformerCodeSequence = human_performer_sequence
    if human_performers_organization_sequence:
        additional_dataset_info.HumanPerformersOrganizationSequence = human_performers_organization_sequence
    return _create_workitem_event_report(
        affected_sop_instance_uid=affected_sop_instance_uid,
        event_type_id=UPSEventType.UPSAssigned,
        input_readiness_state=input_readiness_state,
        procedure_step_state=procedure_step_state,
        additional_dataset_info=additional_dataset_info,
    )


class NotificationService(LoggerMixin):
    """Service for sending notifications via WebSockets."""

    def __init__(self, connection_manager: ConnectionManager) -> None:
        """
        Initialize the NotificationService.

        Args:
            connection_manager: Manager for WebSocket connections.

        """
        self.connection_manager = connection_manager
        self.pending_notifications: dict[str, list[Dataset]] = {}  # subscriber_id -> list of notifications

        # Register for connection events
        self.logger.info("Registering for connection events")
        self.connection_manager.register_connection_callback(self.on_connection_established)

    def queue_state_reports(self, subscription: Subscription) -> None:
        """
        Queue required state reports for a new subscription.

        Args:
            subscription: The newly created subscription.

        """
        ae_title = subscription.ae_title
        workitem_uid = subscription.workitem_uid

        # Initialize the pending notifications queue for this subscriber if needed
        if ae_title not in self.pending_notifications:
            self.pending_notifications[ae_title] = []

        # For a specific UPS instance subscription
        if workitem_uid not in [GLOBAL_SUBSCRIPTION_UID, FILTERED_SUBSCRIPTION_UID]:
            # Get the workitem
            workitem = service_provider.ServiceProvider.get_instance().workitem_repo.get_by_uid(workitem_uid)
            if workitem:
                # Create and queue the state report
                state_report = create_ups_state_report(
                    workitem.uid, workitem.ds.ProcedureStepState, workitem.ds.InputReadinessState
                )
                self.pending_notifications[ae_title].append(state_report)
                self.logger.info(f"Queued state report for specific UPS {workitem_uid} to {ae_title}")

        # For a global subscription with deletion lock
        elif workitem_uid == GLOBAL_SUBSCRIPTION_UID and subscription.deletion_lock:
            # Get all workitems
            workitems = service_provider.ServiceProvider.get_instance().workitem_repo.get_all()
            for workitem in workitems:
                state_report = create_ups_state_report(
                    workitem.uid, workitem.ds.ProcedureStepState, workitem.ds.InputReadinessState
                )
                self.pending_notifications[ae_title].append(state_report)
            self.logger.info(f"Queued {len(workitems)} state reports for global subscription to {ae_title}")

        # For filtered subscription, apply filter to get matching workitems
        elif workitem_uid == FILTERED_SUBSCRIPTION_UID and subscription.filter:
            workitems = service_provider.ServiceProvider.get_instance().workitem_repo.get_all()
            queued_count = 0
            for workitem in workitems:
                if match_query_to_dataset(subscription.filter, workitem.ds):
                    state_report = create_ups_state_report(
                        workitem.uid, workitem.ds.ProcedureStepState, workitem.ds.InputReadinessState
                    )
                    self.pending_notifications[ae_title].append(state_report)
                    queued_count += 1
            self.logger.info(f"Queued {queued_count} state reports for filtered subscription to {ae_title}")
        self.logger.info(f"Total pending notifications for {ae_title}: {len(self.pending_notifications[ae_title])}")

    async def on_connection_established(self, subscriber_id: str) -> None:
        """
        Handle a new WebSocket connection event.

        Args:
            subscriber_id: The ID of the subscriber that established a connection.

        """
        if subscriber_id in self.pending_notifications and self.pending_notifications[subscriber_id]:
            self.logger.info(
                f"Sending {len(self.pending_notifications[subscriber_id])} pending notifications to {subscriber_id}"
            )

            # Send all pending notifications
            pending_count = len(self.pending_notifications[subscriber_id])
            sent_count = 0

            for message in self.pending_notifications[subscriber_id]:
                try:
                    success = await self.connection_manager.send_message(subscriber_id, message.to_json())
                    if success:
                        sent_count += 1
                except Exception as e:
                    self.logger.error(f"Error sending pending notification to {subscriber_id}: {e}")

            self.logger.info(f"Sent {sent_count}/{pending_count} pending notifications to {subscriber_id}")

            # Clear the pending notifications for this subscriber
            self.pending_notifications[subscriber_id] = []

    def notify_creation(self, workitem: WorkItem) -> None:
        """
        Send a notification for workitem creation.

        Note that a UPS State Report should go out when a subscriber (first) subscribes for a specific UPS/workitem.
        Not when the workitem is created/scheduled.  However, when the state *changes* (e.g. from SCHEDULED to IN PROGRESS),
        a UPS State Report should be sent.

        Args:
            workitem: The created workitem.

        """
        event_report_message = create_ups_state_report(
            workitem.uid,
            workitem.ds.ProcedureStepState,
            workitem.ds.InputReadinessState,
        )
        self._send_notification(workitem.uid, event_report_message)
        event_report_message = create_ups_assigned_report(workitem.ds)
        self._send_notification(workitem.uid, event_report_message)

    def _get_element_value_if_present(self, ds: Dataset, element_name: str) -> Any | None:  # noqa: ANN401
        element: DataElement = ds.get(element_name)
        return element.value if element is not None else None

    def notify_status_change(self, workitem: WorkItem) -> None:
        """
        Send a notification for workitem status change.

        Args:
            workitem: The updated workitem.

        """
        event_report_message = None
        affected_sop_instance_uid = workitem.uid
        procedure_step_state: str = workitem.ds.ProcedureStepState
        input_readiness_state: str = workitem.ds.InputReadinessState
        reason_for_cancellation: str | None = self._get_element_value_if_present(workitem.ds, "ReasonForCancellation")

        procedure_step_progress: int | None = None
        progress_description: str | None = None
        contact_uri: str | None = None
        contact_display_name: str | None = None
        if procedure_step_progress_information_sequence := workitem.ds.get("ProcedureStepProgressInformationSequence"):
            seq_item: Dataset = procedure_step_progress_information_sequence[0]
            procedure_step_progress = self._get_element_value_if_present(seq_item, "ProcedureStepProgress")
            progress_description = self._get_element_value_if_present(seq_item, "ProcedureStepProgressDescription")

        if procedure_step_communications_uri_sequence := workitem.ds.get("ProcedureStepCommunicationsURISequence"):
            seq_item: Dataset = procedure_step_communications_uri_sequence[0]
            contact_uri = self._get_element_value_if_present(seq_item, "ContactURI")
            contact_display_name = self._get_element_value_if_present(seq_item, "ContactDisplayName")

        if procedure_step_progress_information_sequence and procedure_step_state != "CANCELED":
            event_report_message = create_ups_progress_report(
                affected_sop_instance_uid=affected_sop_instance_uid,
                procedure_step_state=procedure_step_state,
                input_readiness_state=input_readiness_state,
                procedure_step_progress=procedure_step_progress,
                progress_description=progress_description,
                contact_uri=contact_uri,
                contact_display_name=contact_display_name,
            )
        else:
            event_report_message = create_ups_state_report(
                affected_sop_instance_uid=affected_sop_instance_uid,
                procedure_step_state=procedure_step_state,
                input_readiness_state=input_readiness_state,
                reason_for_cancellation=reason_for_cancellation,
            )

        self._send_notification(workitem.uid, message=event_report_message)

    def _match_on_filter(self, filtered_subscribers: list, workitem_uid: str) -> list:
        # provide filtering of the subscriber based on the filter for the subscriber and the content of the
        # workitem (which will be retrieved based on it's UID)
        self.logger.warning(f"Matching subscribers for workitem UID: {workitem_uid}")
        matching_subscribers = []
        for subscriber_id in filtered_subscribers:
            subscriptions = service_provider.ServiceProvider.get_instance().subscription_service.get_by_ae_title(subscriber_id)

            for subscription in subscriptions:
                self.logger.warning(f"Checking filter for {subscriber_id} for workitem UID: {workitem_uid}")
                self.logger.warning(f"Subscription: {subscription}")
                filter = subscription.filter or Dataset()
                workitem = service_provider.ServiceProvider.get_instance().workitem_repo.get_by_uid(workitem_uid)
                workitem_ds = workitem.ds if hasattr(workitem, "ds") else None
                if filter and workitem_ds and match_query_to_dataset(filter, workitem_ds):
                    self.logger.warning(f"Matched filter for {subscriber_id} for workitem UID: {workitem_uid}")
                    self.logger.warning(f"Filter: {filter}")
                    matching_subscribers.append(subscriber_id)
        return matching_subscribers

    def _send_notification(self, workitem_uid: str, message: Dataset) -> None:
        """
        Send a notification to all subscribers.

        Args:
            workitem_uid: The UID of the workitem.
            message: The message to send.

        """
        subscribers = self.connection_manager.get_subscribers(workitem_uid)
        self.logger.warning(f"Subscribers to specific workitem UID: {subscribers} for workitem UID: {workitem_uid}")
        global_subscribers = self.connection_manager.get_subscribers(GLOBAL_SUBSCRIPTION_UID)
        self.logger.warning(f"Subscribers to global workitem UID: {global_subscribers}")
        filtered_subscribers = self.connection_manager.get_subscribers(FILTERED_SUBSCRIPTION_UID)
        self.logger.warning(f"Subscribers to filtered workitem UID: {filtered_subscribers}")

        if global_subscribers:
            for subscriber in global_subscribers:
                subscribers.add(subscriber)

        if matching_subscribers := self._match_on_filter(filtered_subscribers, workitem_uid):
            for subscriber in matching_subscribers:
                subscribers.add(subscriber)

        self.logger.warning(f"{len(subscribers)} Subscribers: {subscribers} for workitem UID: {workitem_uid}")
        self.logger.debug(f"Sending notification to {len(subscribers)} subscribers for {workitem_uid}")
        for subscriber_id in subscribers:
            subscription = service_provider.ServiceProvider.get_instance().subscription_service.get_by_ae_title(subscriber_id)
            if subscription and subscription[0].suspended:
                self.logger.warning(f"Subscription for {subscriber_id} is suspended, not sending notification")
                continue
            try:
                loop = asyncio.get_event_loop()  # Or however you access your running event loop

                # Fire and forget
                asyncio.run_coroutine_threadsafe(
                    self.connection_manager.send_message(subscriber_id, message=message.to_json()), loop
                )
                # self.connection_manager.send_message(subscriber_id, message=message.to_json())
            except Exception as e:
                self.logger.error(f"Failed to send notification: {e}")
