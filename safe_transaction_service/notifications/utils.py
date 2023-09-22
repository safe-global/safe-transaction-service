import hashlib
import json
from typing import Any, Dict, Optional, Sequence
from uuid import UUID

from django.conf import settings

from eth_account.messages import defunct_hash_message
from hexbytes import HexBytes

from gnosis.eth.utils import fast_keccak

from safe_transaction_service.utils.redis import get_redis


class SafeNotification:
    def __init__(self, address: Optional[str], payload: Dict[str, Any]):
        self.redis = get_redis()
        self.address = address
        self.payload = payload
        self.redis_key = self._get_redis_key(address, payload)
        self.expiration_time_seconds = (
            settings.NOTIFICATIONS_DUPLICATED_EXPIRATION_TIME_SECONDS
        )

    def _get_redis_key(self, address: Optional[str], payload: Dict[str, Any]) -> str:
        """
        :param address:
        :param payload:
        :return: Key built from ``address`` and MD5 hashing the ``payload``
        """
        payload_hash = json.dumps(payload, sort_keys=True)
        # Use MD5 as it's fast and should be enough for this use case
        hex_hash = hashlib.md5(payload_hash.encode()).hexdigest()
        return f"notifications:{address}:{hex_hash}"

    def is_duplicated(self) -> bool:
        """
        :return: ``True`` if payload was already notified, ``False`` otherwise
        """
        return bool(self.redis.get(self.redis_key))

    def set_duplicated(self) -> bool:
        """
        Stores key with an expiration time if not set

        :return: ``True`` if key was not set before, ``False`` otherwise
        """
        return bool(
            self.redis.set(self.redis_key, 1, ex=self.expiration_time_seconds, nx=True)
        )


def mark_notification_as_processed(
    address: Optional[str], payload: Dict[str, Any]
) -> bool:
    """
    :param address:
    :param payload:
    :return: ``True`` if key was not used and was set, ``False`` otherwise
    """
    return SafeNotification(address, payload).set_duplicated()


def calculate_device_registration_hash(
    timestamp: int,
    identifier: UUID,
    cloud_messaging_token: str,
    safes: Sequence[str],
    prefix: str = "gnosis-safe",
    eip191: bool = False,
) -> HexBytes:
    safes_to_str = "".join(sorted(safes))
    str_to_sign = (
        f"{prefix}{timestamp}{identifier}{cloud_messaging_token}{safes_to_str}"
    )
    raw_hash = fast_keccak(str_to_sign.encode())
    if eip191:
        return defunct_hash_message(raw_hash)
    return raw_hash
