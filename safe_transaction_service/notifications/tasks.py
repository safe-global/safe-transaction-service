import pickle
from typing import Any, Dict, Optional, Tuple

from django.conf import settings

from celery import app
from celery.utils.log import get_task_logger
from redis import Redis

from safe_transaction_service.history.models import (MultisigTransaction,
                                                     WebHookType)
from safe_transaction_service.history.utils import close_gevent_db_connection

from .clients.firebase_client import FirebaseClientPool
from .models import FirebaseDevice

logger = get_task_logger(__name__)


def get_redis() -> Redis:
    if not hasattr(get_redis, 'redis'):
        get_redis.redis = Redis.from_url(settings.REDIS_URL)
    return get_redis.redis


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


@app.shared_task()
def send_notification_task(address: Optional[str], payload: Dict[str, Any]) -> Tuple[int, int]:
    try:
        if not (address and payload):  # Both must be present
            return 0

        firebase_devices = FirebaseDevice.objects.filter(
            safes__address=address
        ).exclude(
            cloud_messaging_token=None
        )  # TODO Use cache
        tokens = [firebase_device.cloud_messaging_token for firebase_device in firebase_devices]

        if not (tokens and filter_notification(payload)):
            return 0

        # Make sure notification has not been sent before
        duplicate_notification = DuplicateNotification(address, payload)
        if duplicate_notification.is_duplicated():
            logger.info('Duplicated notification about Safe=%s with payload=%s to tokens=%s', address, payload, tokens)
            return 0

        duplicate_notification.set_duplicated()

        with FirebaseClientPool() as firebase_client:
            logger.info('Sending notification about Safe=%s with payload=%s to tokens=%s', address, payload, tokens)
            success_count, failure_count, invalid_tokens = firebase_client.send_message(tokens, payload)
            if invalid_tokens:
                logger.info('Removing invalid tokens for safe=%s', address)
                FirebaseDevice.objects.filter(
                    cloud_messaging_token__in=invalid_tokens
                ).update(cloud_messaging_token=None)

        return success_count, failure_count
    finally:
        close_gevent_db_connection()
