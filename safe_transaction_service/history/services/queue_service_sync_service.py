# SPDX-License-Identifier: FSL-1.1-MIT
"""
Copy the data written to the Queue Service (multisig transactions, confirmations,
deletions, messages and delegates) into this service, so clients of this API see
it while both services run in parallel.

Every write is done with queryset operations that do not send model signals, so
no event is published: the Queue Service already published its own. Cached views
are cleared explicitly instead.
"""

import json
import logging
import time
from collections.abc import Callable
from functools import cache
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.db.models import Value
from django.db.models.functions import Greatest
from django.utils.dateparse import parse_datetime

import requests
from hexbytes import HexBytes
from kombu import Connection, Exchange, Queue, binding
from kombu.message import Message
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.utils import fast_to_checksum_address
from safe_eth.safe.safe_signature import SafeSignatureType

from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.tokens.clients.base_client import BaseHTTPClient
from safe_transaction_service.utils.ethereum import get_chain_id

from ..cache import CacheSafeTxsView, remove_cache_view_for_addresses
from ..models import (
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
)
from .index_service import _raw_delete

logger = logging.getLogger(__name__)

# AMQP `app_id` the Queue Service sets on the events it publishes
QUEUE_SERVICE_APP_ID = "safe-queue-service"
# Delegates valid for every chain are published with this `chainId`
ALL_CHAINS_CHAIN_ID = "0"
DELEGATE_EVENT_TYPES = ("NEW_DELEGATE", "UPDATED_DELEGATE", "DELETED_DELEGATE")

DELEGATES_PAGE_SIZE = 100

# Proposal route of the Queue Service when a delegate proposed the transaction
PROPOSED_VIA_DELEGATE = "DELEGATE"

# The broker removes the queue, and the messages in it, when nobody reads it for
# this long, so it does not keep events forever once the sync is disabled
QUEUE_TTL_MS = 24 * 60 * 60 * 1000

# How often the sync task runs
QUEUE_SERVICE_SYNC_INTERVAL_SECONDS = 5

# HTTP status codes of the Queue Service while it is restarted or deployed
QUEUE_SERVICE_UNAVAILABLE_STATUS_CODES = (502, 503, 504)

# Log message for events that cannot be stored, used for a log-based metric
SKIPPED_EVENT_LOG_MESSAGE = "Queue Service sync skipped event"


class QueueServiceClient(BaseHTTPClient):
    """
    Read-only client for the Queue Service API
    """

    def __init__(self, base_url: str, request_timeout: int = 5):
        super().__init__(request_timeout=request_timeout)
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> dict[str, Any] | None:
        """
        :param path: Path relative to the API base url
        :return: Decoded JSON response, ``None`` if the element does not exist
        :raises requests.RequestException: if the request fails
        """
        response = self.http_session.get(
            f"{self.base_url}{path}", timeout=self.request_timeout
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_multisig_transaction(self, safe_tx_hash: str) -> dict[str, Any] | None:
        return self._get(f"/api/v1/multisig-transactions/{safe_tx_hash}")

    def get_message(self, message_hash: str) -> dict[str, Any] | None:
        return self._get(f"/api/v1/messages/{message_hash}")

    def get_delegates(self, delegate: str, delegator: str) -> list[dict[str, Any]]:
        """
        :return: Every delegation of the delegator to the delegate, for every
            Safe and chain
        """
        delegates = []
        offset = 0
        while True:
            response = self._get(
                f"/api/v1/delegates?delegate={delegate}&delegator={delegator}"
                f"&offset={offset}&limit={DELEGATES_PAGE_SIZE}"
            )
            delegates.extend(response["results"])
            if not response["next"] or not response["results"]:
                return delegates
            offset += len(response["results"])


class SkippedEventException(Exception):
    """
    The event cannot be stored in this service
    """


def build_origin(**fields: str | None) -> dict[str, str]:
    """
    :return: ``origin`` of this service with the non-empty fields
    """
    return {key: value for key, value in fields.items() if value}


def build_confirmation_fields(confirmation: dict[str, Any]) -> dict[str, Any]:
    """
    :param confirmation: Confirmation of a transaction or a message in the Queue Service
    :return: Fields shared by ``MultisigConfirmation`` and ``SafeMessageConfirmation``
    """
    return {
        "owner": fast_to_checksum_address(confirmation["owner"]),
        "signature": HexBytes(confirmation["signature"]),
        "signature_type": SafeSignatureType[confirmation["signatureType"]].value,
        "created": parse_datetime(confirmation["created"]),
        "modified": parse_datetime(confirmation["modified"]),
    }


@cache
def get_queue_service_sync_service() -> "QueueServiceSyncService":
    return QueueServiceSyncService(
        QueueServiceClient(settings.QUEUE_SERVICE_URL),
        Connection(settings.EVENTS_QUEUE_URL),
        str(get_chain_id()),
    )


class QueueServiceSyncService:
    def __init__(
        self,
        queue_service_client: QueueServiceClient,
        connection: Connection,
        chain_id: str,
    ):
        self.queue_service_client = queue_service_client
        self.connection = connection
        self.chain_id = chain_id
        self.event_handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "PENDING_MULTISIG_TRANSACTION": self.sync_multisig_transaction,
            "NEW_CONFIRMATION": self.sync_multisig_transaction,
            "DELETED_MULTISIG_TRANSACTION": self.sync_deleted_multisig_transaction,
            "MESSAGE_CREATED": self.sync_message,
            "MESSAGE_CONFIRMATION": self.sync_message,
            "NEW_DELEGATE": self.sync_delegate,
            "UPDATED_DELEGATE": self.sync_delegate,
            "DELETED_DELEGATE": self.sync_delegate,
        }
        # The bindings select the events: every event of this chain, and the
        # delegates valid for every chain
        exchange = Exchange(
            settings.EVENTS_QUEUE_TOPIC_EXCHANGE_NAME, type="topic", durable=True
        )
        routing_keys = [
            f"{chain_id}.{event_type}.*" for event_type in self.event_handlers
        ] + [
            f"{ALL_CHAINS_CHAIN_ID}.{event_type}.*"
            for event_type in DELEGATE_EVENT_TYPES
        ]
        self.queue = Queue(
            f"safe-transaction-service-{chain_id}-queue-sync",
            exchange=exchange,
            bindings=[
                binding(exchange, routing_key=routing_key)
                for routing_key in routing_keys
            ],
            durable=True,
            queue_arguments={"x-expires": QUEUE_TTL_MS, "x-message-ttl": QUEUE_TTL_MS},
        )
        # Declaring the queue and its bindings takes a broker round trip each,
        # so it is done once per connection
        self.queue_declared = False

    def sync(self, time_limit_seconds: float) -> int:
        """
        Process the pending events of the queue until it is empty, the time
        limit is reached, or the Queue Service cannot be reached.

        :param time_limit_seconds: Stop taking new events after this time
        :return: Number of messages consumed, including the ones from other
            publishers, which are ignored
        """
        deadline = time.monotonic() + time_limit_seconds
        processed = 0
        try:
            with self.connection.channel() as channel:
                queue = self.queue(channel)
                if not self.queue_declared:
                    queue.declare()
                    self.queue_declared = True
                while time.monotonic() < deadline:
                    message = queue.get(no_ack=False)
                    if message is None:
                        break
                    if not self.process_message(message):
                        break
                    processed += 1
        except self.connection.connection_errors + self.connection.channel_errors:
            logger.warning("Cannot read events from the broker", exc_info=True)
            # Drop the broken connection, the next run opens a new one and
            # declares the queue again
            self.connection.collect()
            self.queue_declared = False
        return processed

    def process_message(self, message: Message) -> bool:
        """
        Process one message and acknowledge it. When the Queue Service cannot be
        reached, the message is requeued and the run stops. Other unexpected
        errors requeue the message once, and drop it if it fails again after
        being redelivered, so a message that always fails cannot block the queue.

        :param message:
        :return: ``False`` if the sync must stop for this run, ``True`` otherwise
        """
        if message.properties.get("app_id") != QUEUE_SERVICE_APP_ID:
            message.ack()
            return True

        payload: dict[str, Any] | str = message.body
        try:
            payload = json.loads(message.body)
            with transaction.atomic():
                self.event_handlers[payload["type"]](payload)
        except requests.RequestException as exc:
            if not self._is_queue_service_unavailable(exc):
                return self._retry_once(message, payload, exc)
            logger.warning(
                "Queue Service cannot be reached, requeueing event %s: %s",
                payload,
                exc,
            )
            message.requeue()
            return False
        except (
            SkippedEventException,
            IntegrityError,
            DataError,
            ValidationError,
            KeyError,
            ValueError,
            TypeError,
        ) as exc:
            self._log_skipped_event(payload, repr(exc))
        except Exception as exc:
            return self._retry_once(message, payload, exc)
        message.ack()
        return True

    @staticmethod
    def _is_queue_service_unavailable(exc: requests.RequestException) -> bool:
        return isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
            exc.response is not None
            and exc.response.status_code in QUEUE_SERVICE_UNAVAILABLE_STATUS_CODES
        )

    def _retry_once(
        self, message: Message, payload: dict[str, Any] | str, exc: Exception
    ) -> bool:
        """
        Requeue the message, or drop it if it was already redelivered.

        :return: ``False`` if the sync must stop for this run, ``True`` otherwise
        """
        if message.delivery_info.get("redelivered"):
            self._log_skipped_event(payload, repr(exc))
            message.ack()
            return True
        logger.warning("Cannot process event %s, requeueing it", payload, exc_info=True)
        message.requeue()
        return False

    def _log_skipped_event(self, payload: dict[str, Any] | str, reason: str) -> None:
        logger.warning(
            SKIPPED_EVENT_LOG_MESSAGE,
            extra={"extra_data": {"event": payload, "reason": reason}},
        )

    def _filter_this_chain(
        self, element_data: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """
        Safes older than v1.3.0 build the same hash on every chain, and the
        Queue Service stores one element per hash, so an element of another
        chain is missing for this one.

        :param element_data: Transaction or message from the Queue Service
        :return: ``element_data`` if it belongs to this chain, ``None`` otherwise
        """
        if element_data is None or str(element_data["chainId"]) != self.chain_id:
            return None
        return element_data

    def _remove_multisig_transactions_cache(self, safe: str) -> None:
        if settings.CACHE_VIEW_DEFAULT_TIMEOUT:
            remove_cache_view_for_addresses(
                CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY, [safe]
            )

    def sync_multisig_transaction(self, payload: dict[str, Any]) -> None:
        """
        Store the transaction if it does not exist and add its missing
        confirmations. A transaction that already exists is not updated, as the
        Queue Service does not hold every field of this service.

        :param payload: ``PENDING_MULTISIG_TRANSACTION`` or ``NEW_CONFIRMATION`` event
        """
        tx_data = self._filter_this_chain(
            self.queue_service_client.get_multisig_transaction(payload["safeTxHash"])
        )
        # Executed transactions are stored by the indexer
        if tx_data is None or tx_data["txHash"]:
            return None

        safe_tx_hash = HexBytes(tx_data["safeTxHash"])
        existing_tx = (
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash)
            .values("ethereum_tx_id", "trusted")
            .first()
        )
        if existing_tx and existing_tx["ethereum_tx_id"]:
            return None

        if not existing_tx:
            MultisigTransaction.objects.bulk_create(
                [
                    MultisigTransaction(
                        safe_tx_hash=safe_tx_hash,
                        safe=tx_data["safe"],
                        proposer=tx_data["proposer"],
                        proposed_by_delegate=(
                            tx_data["proposedBy"]
                            if tx_data["proposedVia"] == PROPOSED_VIA_DELEGATE
                            else None
                        ),
                        to=tx_data["to"] or NULL_ADDRESS,
                        value=int(tx_data["value"]),
                        data=HexBytes(tx_data["data"] or b"") or None,
                        operation=tx_data["operation"],
                        safe_tx_gas=int(tx_data["safeTxGas"]),
                        base_gas=int(tx_data["baseGas"]),
                        gas_price=int(tx_data["gasPrice"]),
                        gas_token=tx_data["gasToken"] or NULL_ADDRESS,
                        refund_receiver=tx_data["refundReceiver"] or NULL_ADDRESS,
                        nonce=int(tx_data["nonce"]),
                        origin=build_origin(
                            url=tx_data["originUrl"],
                            name=tx_data["originName"],
                            note=tx_data["notes"],
                        ),
                        trusted=True,
                        created=parse_datetime(tx_data["created"]),
                        modified=parse_datetime(tx_data["modified"]),
                    )
                ],
                ignore_conflicts=True,
            )
            # Link the confirmations stored before the transaction
            MultisigConfirmation.objects.without_transaction().filter(
                multisig_transaction_hash=safe_tx_hash
            ).update(multisig_transaction_id=safe_tx_hash)

        existing_owners = set(
            MultisigConfirmation.objects.filter(
                multisig_transaction_hash=safe_tx_hash
            ).values_list("owner", flat=True)
        )
        new_confirmations = [
            MultisigConfirmation(
                multisig_transaction_id=safe_tx_hash,
                multisig_transaction_hash=safe_tx_hash,
                **build_confirmation_fields(confirmation),
            )
            for confirmation in tx_data["confirmations"]
            # On-chain approvals are stored by the indexer
            if confirmation["signatureType"] != SafeSignatureType.APPROVED_HASH.name
            and fast_to_checksum_address(confirmation["owner"]) not in existing_owners
        ]
        if new_confirmations:
            MultisigConfirmation.objects.bulk_create(
                new_confirmations, ignore_conflicts=True
            )

        # The Queue Service only holds valid proposals, so the transaction is
        # trusted. A new confirmation also sets `modified`, same as a
        # confirmation sent to this service
        updated_tx = not existing_tx or not existing_tx["trusted"] or new_confirmations
        if existing_tx and updated_tx:
            fields = {"trusted": True}
            if new_confirmations:
                fields["modified"] = Greatest(
                    "modified",
                    Value(
                        max(confirmation.created for confirmation in new_confirmations)
                    ),
                )
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).update(
                **fields
            )

        if updated_tx:
            self._remove_multisig_transactions_cache(tx_data["safe"])

    def sync_deleted_multisig_transaction(self, payload: dict[str, Any]) -> None:
        """
        Delete the transaction if it is not executed and it no longer exists in
        the Queue Service.

        :param payload: ``DELETED_MULTISIG_TRANSACTION`` event
        """
        if self._filter_this_chain(
            self.queue_service_client.get_multisig_transaction(payload["safeTxHash"])
        ):
            return None

        safe_tx_hash = HexBytes(payload["safeTxHash"])
        queryset = MultisigTransaction.objects.filter(
            safe_tx_hash=safe_tx_hash, ethereum_tx=None
        )
        safe = queryset.values_list("safe", flat=True).first()
        if not safe:
            return None

        # `delete()` would send `post_delete` and publish an event
        _raw_delete(
            MultisigConfirmation.objects.filter(multisig_transaction_id=safe_tx_hash)
        )
        _raw_delete(queryset)
        self._remove_multisig_transactions_cache(safe)

    def sync_message(self, payload: dict[str, Any]) -> None:
        """
        Store the message if it does not exist and add its missing confirmations.

        :param payload: ``MESSAGE_CREATED`` or ``MESSAGE_CONFIRMATION`` event
        """
        message_data = self._filter_this_chain(
            self.queue_service_client.get_message(payload["messageHash"])
        )
        if message_data is None:
            return None

        message_hash = HexBytes(message_data["messageHash"])
        SafeMessage.objects.bulk_create(
            [
                SafeMessage(
                    message_hash=message_hash,
                    safe=message_data["safe"],
                    message=message_data["message"],
                    proposed_by=message_data["proposer"],
                    origin=build_origin(
                        url=message_data["originUrl"],
                        name=message_data["originName"],
                    ),
                    created=parse_datetime(message_data["created"]),
                    modified=parse_datetime(message_data["modified"]),
                )
            ],
            ignore_conflicts=True,
        )

        existing_owners = set(
            SafeMessageConfirmation.objects.filter(
                safe_message_id=message_hash
            ).values_list("owner", flat=True)
        )
        new_confirmations = [
            SafeMessageConfirmation(
                safe_message_id=message_hash,
                **build_confirmation_fields(confirmation),
            )
            for confirmation in message_data["confirmations"]
            if fast_to_checksum_address(confirmation["owner"]) not in existing_owners
        ]
        if new_confirmations:
            SafeMessageConfirmation.objects.bulk_create(
                new_confirmations, ignore_conflicts=True
            )
            SafeMessage.objects.filter(message_hash=message_hash).update(
                modified=Greatest(
                    "modified",
                    Value(
                        max(confirmation.created for confirmation in new_confirmations)
                    ),
                )
            )

    def sync_delegate(self, payload: dict[str, Any]) -> None:
        """
        Set the delegate of the event to its current state in the Queue Service.
        This service has no chain for delegates: a delegate valid for every
        chain and one valid for this chain are the same row, which exists while
        one of them exists in the Queue Service. The Queue Service does not store
        an expiry date.

        :param payload: ``NEW_DELEGATE``, ``UPDATED_DELEGATE`` or
            ``DELETED_DELEGATE`` event
        :raises SkippedEventException: if the Safe of the delegate is not indexed
        """
        safe = payload.get("address")
        if safe and not SafeContract.objects.filter(address=safe).exists():
            # A delegate for every chain is expected for Safes not on this chain
            if payload["chainId"] == ALL_CHAINS_CHAIN_ID:
                return None
            raise SkippedEventException(f"Safe {safe} is not indexed")

        current_delegates = [
            delegate
            for delegate in self.queue_service_client.get_delegates(
                payload["delegate"], payload["delegator"]
            )
            if (delegate["safe"] and fast_to_checksum_address(delegate["safe"])) == safe
            and (
                delegate["chainId"] is None or str(delegate["chainId"]) == self.chain_id
            )
        ]
        queryset = SafeContractDelegate.objects.filter(
            safe_contract_id=safe,
            delegate=payload["delegate"],
            delegator=payload["delegator"],
        )
        if not current_delegates:
            # `delete()` would send `post_delete` and publish an event
            _raw_delete(queryset)
            return None

        # The delegate of this chain is more specific than the one for every chain
        current_delegate = min(
            current_delegates, key=lambda delegate: delegate["chainId"] is None
        )
        fields = {"label": current_delegate["label"] or "", "expiry_date": None}
        # `update_or_create` would send `post_save`. A unique index with a null
        # `safe_contract` never conflicts, so `bulk_create` cannot upsert
        if not queryset.update(**fields):
            SafeContractDelegate.objects.bulk_create(
                [
                    SafeContractDelegate(
                        safe_contract_id=safe,
                        delegate=payload["delegate"],
                        delegator=payload["delegator"],
                        **fields,
                    )
                ]
            )
