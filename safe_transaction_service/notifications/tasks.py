from typing import Any, Dict, Optional, Tuple

from celery import app
from celery.utils.log import get_task_logger

from safe_transaction_service.history.models import WebHookType

from .clients.firebase_client import FirebaseProvider
from .models import FirebaseDevice

logger = get_task_logger(__name__)


def filter_notification(payload: Dict[str, Any]) -> bool:
    """
    :param payload: Notification payload
    :return: `True` if payload is valid, `False` otherwise
    """
    if not payload:
        # Don't send notifications for empty payload (it shouldn't happen)
        return False
    elif payload.get('type', '') == WebHookType.PENDING_MULTISIG_TRANSACTION.name:
        # Don't send notifications for pending multisig transactions
        return False
    elif payload.get('type', '') == WebHookType.NEW_CONFIRMATION.name:
        # If MultisigTransaction is executed don't notify about a new confirmation
        # try:
        #     return not MultisigTransaction.objects.get(safe_tx_hash=payload.get('safeTxHash')).executed
        # except MultisigTransaction.DoesNotExist:
        #    pass

        # All confirmations are disabled for now
        return False

    return True

@app.shared_task()
def send_notification_task(address: Optional[str], payload: Dict[str, Any]) -> Tuple[int, int]:
    if not (address and payload):  # Both must be present
        return 0

    firebase_client = FirebaseProvider()
    firebase_devices = FirebaseDevice.objects.filter(
        safes__address=address
    ).exclude(
        cloud_messaging_token=None
    )  # TODO Use cache
    tokens = [firebase_device.cloud_messaging_token for firebase_device in firebase_devices]

    if not (tokens and filter_notification(payload)):
        return 0

    logger.info('Sending notification about Safe=%s with payload=%s to tokens=%s', address, payload, tokens)
    success_count, failure_count, invalid_tokens = firebase_client.send_message(tokens, payload)
    if invalid_tokens:
        logger.info('Removing invalid tokens for safe=%s', address)
        FirebaseDevice.objects.filter(cloud_messaging_token__in=invalid_tokens).update(cloud_messaging_token=None)

    return success_count, failure_count
