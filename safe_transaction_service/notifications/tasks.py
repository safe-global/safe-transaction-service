from typing import Any, Dict, Optional, Tuple

from celery import app
from celery.utils.log import get_task_logger

from safe_transaction_service.history.models import (
    MultisigConfirmation,
    MultisigTransaction,
    SafeContractDelegate,
    SafeLastStatus,
    WebHookType,
)
from safe_transaction_service.utils.ethereum import get_chain_id
from safe_transaction_service.utils.utils import close_gevent_db_connection_decorator

from .clients.firebase_client import FirebaseClientPool
from .models import FirebaseDevice, FirebaseDeviceOwner
from .utils import mark_notification_as_processed

logger = get_task_logger(__name__)


def filter_notification(payload: Dict[str, Any]) -> bool:
    """
    :param payload: Notification payload
    :return: `True` if payload is valid, `False` otherwise
    """
    payload_type = payload.get("type", "")
    if not payload_type:
        # Don't send notifications for empty payload (it shouldn't happen)
        return False
    elif payload_type == WebHookType.PENDING_MULTISIG_TRANSACTION.name:
        # Don't send notifications for pending multisig transactions
        return False
    elif payload_type == WebHookType.NEW_CONFIRMATION.name:
        # If MultisigTransaction is executed don't notify about a new confirmation
        # try:
        #     return not MultisigTransaction.objects.get(safe_tx_hash=payload.get('safeTxHash')).executed
        # except MultisigTransaction.DoesNotExist:
        #    pass

        # All confirmations are disabled for now
        return False
    elif payload_type in (
        WebHookType.OUTGOING_ETHER.name,
        WebHookType.OUTGOING_TOKEN.name,
    ):
        return False
    elif payload_type in (
        WebHookType.INCOMING_ETHER.name,
        WebHookType.INCOMING_TOKEN.name,
    ):
        # Only send ETH/token pushes when they weren't triggered by a tx from some account other than the Safe.
        # If Safe triggers a transaction to transfer Ether/Tokens into itself, 2 notifications will be generated, and
        # that's not desired
        return not MultisigTransaction.objects.filter(
            ethereum_tx=payload["txHash"], safe=payload["address"]
        ).exists()

    return True


def is_pending_multisig_transaction(payload: Dict[str, Any]) -> bool:
    return payload.get("type", "") == WebHookType.PENDING_MULTISIG_TRANSACTION.name


@app.shared_task()
@close_gevent_db_connection_decorator
def send_notification_task(
    address: Optional[str], payload: Dict[str, Any]
) -> Tuple[int, int]:
    """
    :param address:
    :param payload:
    :return: Tuple with the number of successful and failed notifications sent
    """
    if not (address and payload):  # Both must be present
        return 0, 0

    # Make sure notification has not been sent before
    if not mark_notification_as_processed(address, payload):
        # Notification was processed already
        logger.info(
            "Duplicated notification about Safe=%s with payload=%s",
            address,
            payload,
        )
        return 0, 0

    tokens = list(
        FirebaseDevice.objects.filter(safes__address=address)
        .exclude(cloud_messaging_token=None)
        .values_list("cloud_messaging_token", flat=True)
    )  # TODO Use cache

    if is_pending_multisig_transaction(payload):
        send_notification_owner_task.delay(address, payload["safeTxHash"])

    if not (tokens and filter_notification(payload)):
        return 0, 0

    with FirebaseClientPool() as firebase_client:
        logger.info(
            "Sending notification about Safe=%s with payload=%s to tokens=%s",
            address,
            payload,
            tokens,
        )
        success_count, failure_count, invalid_tokens = firebase_client.send_message(
            tokens, payload
        )
        if invalid_tokens:
            logger.info(
                "Removing invalid tokens for safe=%s. Tokens=%s",
                address,
                invalid_tokens,
            )
            FirebaseDevice.objects.filter(
                cloud_messaging_token__in=invalid_tokens
            ).update(cloud_messaging_token=None)

    return success_count, failure_count


@app.shared_task()
@close_gevent_db_connection_decorator
def send_notification_owner_task(address: str, safe_tx_hash: str) -> Tuple[int, int]:
    """
    Send a confirmation request to an owner

    :param address: Safe address
    :param safe_tx_hash: Hash of the safe tx
    :return: Tuple with the number of successful and failed notifications sent
    """
    assert safe_tx_hash, "Safe tx hash was not provided"

    try:
        safe_last_status = SafeLastStatus.objects.get_or_generate(address)
    except SafeLastStatus.DoesNotExist:
        logger.info("Cannot find threshold information for safe=%s", address)
        return 0, 0

    if safe_last_status.threshold == 1:
        logger.info(
            "No need to send confirmation notification for safe=%s with threshold=1",
            address,
        )
        return 0, 0

    confirmed_owners = MultisigConfirmation.objects.filter(
        multisig_transaction_id=safe_tx_hash
    ).values_list("owner", flat=True)

    if safe_last_status.threshold <= len(confirmed_owners):
        # No need for more confirmations
        logger.info(
            "Multisig transaction with safe-tx-hash=%s for safe=%s does not require more confirmations",
            safe_tx_hash,
            address,
        )
        return 0, 0

    # Get cloud messaging token for missing owners
    owners_to_notify = set(safe_last_status.owners) - set(confirmed_owners)
    if not owners_to_notify:
        return 0, 0

    # Delegates must be notified too
    delegates = SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
        address, owners_to_notify
    )
    users_to_notify = delegates | owners_to_notify

    tokens = FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
        address, users_to_notify
    )

    if not tokens:
        logger.info(
            "No cloud messaging tokens found for owners %s or delegates %s to sign safe-tx-hash=%s for safe=%s",
            owners_to_notify,
            delegates,
            safe_tx_hash,
            address,
        )
        return 0, 0

    payload = {
        "type": WebHookType.CONFIRMATION_REQUEST.name,
        "address": address,
        "safeTxHash": safe_tx_hash,
        "chainId": str(get_chain_id()),
    }

    # Make sure notification has not been sent before
    if not mark_notification_as_processed(address, payload):
        # Notification was processed already
        logger.info(
            "Duplicated notification about Safe=%s with payload=%s",
            address,
            payload,
        )
        return 0, 0

    with FirebaseClientPool() as firebase_client:
        logger.info(
            "Sending notification about Safe=%s with payload=%s to tokens=%s",
            address,
            payload,
            tokens,
        )
        success_count, failure_count, invalid_tokens = firebase_client.send_message(
            tokens, payload
        )
        if invalid_tokens:
            logger.info(
                "Removing invalid tokens for owners of safe=%s. Tokens=%s",
                address,
                invalid_tokens,
            )
            FirebaseDevice.objects.filter(
                cloud_messaging_token__in=invalid_tokens
            ).update(cloud_messaging_token=None)

    return success_count, failure_count
