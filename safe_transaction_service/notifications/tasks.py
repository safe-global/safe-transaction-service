import pickle
from typing import Any, Dict, Optional, Tuple

from celery import app
from celery.utils.log import get_task_logger

from safe_transaction_service.history.models import (MultisigConfirmation,
                                                     MultisigTransaction,
                                                     SafeStatus, WebHookType)
from safe_transaction_service.history.utils import (close_gevent_db_connection,
                                                    get_redis)

from .clients.firebase_client import FirebaseClientPool
from .models import FirebaseDevice, FirebaseDeviceOwner

logger = get_task_logger(__name__)


class DuplicateNotification:
    def __init__(self, address: Optional[str], payload: Dict[str, Any]):
        self.redis = get_redis()
        self.address = address
        self.payload = payload
        self.redis_payload = self._get_redis_payload(address, payload)

    def _get_redis_payload(self, address: Optional[str], payload: Dict[str, Any]):
        return f'notifications:{address}:'.encode() + pickle.dumps(payload)

    def is_duplicated(self) -> bool:
        """
        :return: True if payload was already notified, False otherwise
        """
        return bool(self.redis.get(self.redis_payload))

    def set_duplicated(self) -> bool:
        """
        Stores notification with an expiration time of 5 minutes
        :return:
        """
        return self.redis.set(self.redis_payload, 1, ex=5 * 60)


def filter_notification(payload: Dict[str, Any]) -> bool:
    """
    :param payload: Notification payload
    :return: `True` if payload is valid, `False` otherwise
    """
    payload_type = payload.get('type', '')
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
    elif payload_type in (WebHookType.INCOMING_ETHER.name, WebHookType.INCOMING_TOKEN.name):
        # Only send ETH/token pushes when they weren't triggered by a tx from some account other than the Safe.
        # If Safe triggers a transaction to transfer Ether/Tokens into itself, 2 notifications will be generated, and
        # that's not desired
        return not MultisigTransaction.objects.filter(
            ethereum_tx=payload['txHash'],
            safe=payload['address']
        ).exists()

    return True


def is_pending_multisig_transaction(payload: Dict[str, Any]) -> bool:
    return payload.get('type', '') == WebHookType.PENDING_MULTISIG_TRANSACTION.name


@app.shared_task()
def send_notification_task(address: Optional[str], payload: Dict[str, Any]) -> Tuple[int, int]:
    """
    :param address:
    :param payload:
    :return: Tuple with the number of successful and failed notifications sent
    """
    if not (address and payload):  # Both must be present
        return 0, 0

    try:
        firebase_devices = FirebaseDevice.objects.filter(
            safes__address=address
        ).exclude(
            cloud_messaging_token=None
        )  # TODO Use cache
        tokens = [firebase_device.cloud_messaging_token for firebase_device in firebase_devices]

        if is_pending_multisig_transaction(payload):
            send_notification_owner_task.delay(address, payload['safeTxHash'])

        if not (tokens and filter_notification(payload)):
            return 0, 0

        # Make sure notification has not been sent before
        duplicate_notification = DuplicateNotification(address, payload)
        if duplicate_notification.is_duplicated():
            logger.info('Duplicated notification about Safe=%s with payload=%s to tokens=%s', address, payload, tokens)
            return 0, 0

        duplicate_notification.set_duplicated()

        with FirebaseClientPool() as firebase_client:
            logger.info('Sending notification about Safe=%s with payload=%s to tokens=%s', address, payload, tokens)
            success_count, failure_count, invalid_tokens = firebase_client.send_message(tokens, payload)
            if invalid_tokens:
                logger.info('Removing invalid tokens for safe=%s. Tokens=%s', address, invalid_tokens)
                FirebaseDevice.objects.filter(
                    cloud_messaging_token__in=invalid_tokens
                ).update(cloud_messaging_token=None)

        return success_count, failure_count
    finally:
        close_gevent_db_connection()


@app.shared_task()
def send_notification_owner_task(address: str, safe_tx_hash: str):
    """
    Send a confirmation request to an owner
    :param address: Safe address
    :param safe_tx_hash: Hash of the safe tx
    :return: Tuple with the number of successful and failed notifications sent
    """
    assert safe_tx_hash, 'Safe tx hash was not provided'

    try:
        confirmed_owners = MultisigConfirmation.objects.filter(
            multisig_transaction_id=safe_tx_hash
        ).values_list('owner', flat=True)
        safe_status = SafeStatus.objects.last_for_address(address)

        if not safe_status:
            logger.info('Cannot find threshold information for safe=%s', address)
            return 0, 0

        if safe_status.threshold == 1:
            logger.info('No need to send confirmation notification for safe=%s with threshold=1', address)
            return 0, 0

        if safe_status.threshold <= len(confirmed_owners):
            # No need for more confirmations
            logger.info('Multisig transaction with safe-tx-hash=%s for safe=%s does not require more confirmations',
                        safe_tx_hash, address)
            return 0, 0

        # Get cloud messaging token for missing owners
        owners_to_notify = set(safe_status.owners) - set(confirmed_owners)
        tokens = FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(address, owners_to_notify)

        if not tokens:
            logger.info('No cloud messaging tokens found for needed owners %s to sign safe-tx-hash=%s for safe=%s',
                        owners_to_notify, safe_tx_hash, address)
            return 0, 0

        payload = {
            'type': WebHookType.CONFIRMATION_REQUEST.name,
            'address': address,
            'safeTxHash': safe_tx_hash,
        }
        # Make sure notification has not been sent before
        duplicate_notification = DuplicateNotification(address, payload)
        if duplicate_notification.is_duplicated():
            logger.info('Duplicated notification about Safe=%s with payload=%s to tokens=%s', address, payload, tokens)
            return 0, 0

        duplicate_notification.set_duplicated()

        with FirebaseClientPool() as firebase_client:
            logger.info('Sending notification about Safe=%s with payload=%s to tokens=%s', address, payload, tokens)
            success_count, failure_count, invalid_tokens = firebase_client.send_message(tokens, payload)
            if invalid_tokens:
                logger.info('Removing invalid tokens for owners of safe=%s. Tokens=%s', address, invalid_tokens)
                FirebaseDevice.objects.filter(
                    cloud_messaging_token__in=invalid_tokens
                ).update(cloud_messaging_token=None)

        return success_count, failure_count
    finally:
        close_gevent_db_connection()
