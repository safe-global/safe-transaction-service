# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.conf import settings
from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from safe_transaction_service.history.services.event_service import build_event_payload
from safe_transaction_service.history.signals import send_payloads_on_commit
from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)

logger = logging.getLogger(__name__)


@receiver(
    post_save,
    sender=SafeMessage,
    dispatch_uid="safe_message.process_event",
)
@receiver(
    post_save,
    sender=SafeMessageConfirmation,
    dispatch_uid="safe_message_confirmation.process_event",
)
def process_event(
    sender: type[Model],
    instance: SafeMessage | SafeMessageConfirmation,
    created: bool,
    **kwargs,
) -> None:
    if settings.DISABLE_SERVICE_EVENTS:
        return None

    logger.debug("Start building payloads for created=%s object=%s", created, instance)
    payloads = build_event_payload(sender, instance)
    logger.debug(
        "End building payloads %s for created=%s object=%s", payloads, created, instance
    )
    send_payloads_on_commit([payload for payload in payloads if payload.get("address")])
