import logging
from typing import Type, Union

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from safe_transaction_service.events.services.queue_service import get_queue_service
from safe_transaction_service.history.services.notification_service import (
    build_event_payload,
)
from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)

logger = logging.getLogger(__name__)


@receiver(
    post_save,
    sender=SafeMessage,
    dispatch_uid="safe_message.process_notification_event",
)
@receiver(
    post_save,
    sender=SafeMessageConfirmation,
    dispatch_uid="safe_message_confirmation.process_notification_event",
)
def process_notification_event(
    sender: Type[Model],
    instance: Union[
        SafeMessage,
        SafeMessageConfirmation,
    ],
    created: bool,
    **kwargs,
) -> None:
    logger.debug("Start building payloads for created=%s object=%s", created, instance)
    payloads = build_event_payload(sender, instance)
    logger.debug(
        "End building payloads %s for created=%s object=%s", payloads, created, instance
    )
    for payload in payloads:
        if address := payload.get("address"):
            logger.debug(
                "Triggering send_notification tasks for created=%s object=%s",
                created,
                instance,
            )
            queue_service = get_queue_service()
            queue_service.send_event(payload)
        else:
            logger.debug(
                "Notification will not be sent for created=%s object=%s",
                created,
                instance,
            )
