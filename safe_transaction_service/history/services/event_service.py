# SPDX-License-Identifier: FSL-1.1-MIT
"""
Build event payloads for the queue and publish them
"""

import dataclasses
from datetime import timedelta
from logging import getLogger
from typing import Any, Literal, TypedDict

from django.conf import settings
from django.db.models import Model
from django.utils import timezone

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.safe.safe_signature import SafeSignatureType
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.events.services.queue_service import get_queue_service
from safe_transaction_service.history.helpers import build_transfer_unique_id
from safe_transaction_service.history.models import (
    ERC20Transfer,
    ERC721Transfer,
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
    SafeLastStatus,
    TokenTransfer,
    TransactionServiceEventType,
)
from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.tokens.services import TokenServiceProvider
from safe_transaction_service.utils.ethereum import get_chain_id

logger = getLogger(__name__)

# Events are only sent for data at most this old, so reindexing does not send
# them again
EVENT_MAX_AGE_MINUTES = 60
EVENT_MAX_AGE = timedelta(minutes=EVENT_MAX_AGE_MINUTES)

# Transient (non-DB) attributes set by the indexers on transfer / ether ``InternalTx``
# instances, telling whether the `to` / `_from` side is a tracked Safe. Used by
# `build_event_payload` to only emit the directional event whose side is a Safe.
TO_IS_A_SAFE_ATTR = "_to_is_a_safe"
FROM_IS_A_SAFE_ATTR = "_from_is_a_safe"


def set_safe_membership(
    instance: TokenTransfer | InternalTx,
    to_is_a_safe: bool,
    from_is_a_safe: bool,
) -> None:
    """
    Annotate a ``TokenTransfer`` / ether ``InternalTx`` with whether its `to` / `_from`
    side is a tracked Safe, so `build_event_payload` only emits the directional
    event for the Safe side.

    Called by the indexers at index time (where Safe membership is known in memory). The
    attribute is transient; it survives to the `post_bulk_create` signal because the same
    instance is passed through (see ``BulkCreateSignalMixin.bulk_create``).

    :param instance: ``TokenTransfer`` or ether ``InternalTx`` about to be stored
    :param to_is_a_safe: whether ``instance.to`` is a tracked Safe
    :param from_is_a_safe: whether ``instance._from`` is a tracked Safe
    :return:
    """
    setattr(instance, TO_IS_A_SAFE_ATTR, to_is_a_safe)
    setattr(instance, FROM_IS_A_SAFE_ATTR, from_is_a_safe)


def _filter_not_safe_transfers(
    instance: TokenTransfer | InternalTx,
    incoming_payload: dict[str, Any],
    outgoing_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Keep only the directional payloads whose addressed side is a tracked Safe.

    ``INCOMING_*`` is addressed by ``instance.to`` and gated by ``_to_is_a_safe``;
    ``OUTGOING_*`` by ``instance._from`` and gated by ``_from_is_a_safe``. The indexers
    annotate both attributes (each possibly ``False`` when that side is not a Safe).

    If both attributes are absent, the instance reached payload building without going
    through an annotating indexer: emit nothing and log an error so the gap is visible.

    :param instance: ``TokenTransfer`` or ether ``InternalTx`` being processed
    :param incoming_payload: payload addressed to ``instance.to``
    :param outgoing_payload: payload addressed to ``instance._from``
    :return: the subset of payloads that should be emitted
    """
    to_is_a_safe = getattr(instance, TO_IS_A_SAFE_ATTR, None)
    from_is_a_safe = getattr(instance, FROM_IS_A_SAFE_ATTR, None)

    if to_is_a_safe is None and from_is_a_safe is None:
        identifier = (
            instance.trace_address
            if isinstance(instance, InternalTx)
            else instance.log_index
        )
        logger.error(
            "Lacking metadata to build event for transfer with hash=%s identifier=%s",
            to_0x_hex_str(HexBytes(instance.ethereum_tx_id)),
            identifier,
        )
        return []

    payloads: list[dict[str, Any]] = []
    if to_is_a_safe:
        payloads.append(incoming_payload)
    if from_is_a_safe:
        payloads.append(outgoing_payload)
    return payloads


def build_event_payload(
    sender: type[Model],
    instance: TokenTransfer
    | InternalTx
    | MultisigConfirmation
    | MultisigTransaction
    | SafeMessage
    | SafeMessageConfirmation,
    deleted: bool = False,
) -> list[dict[str, Any]]:
    """
    :param sender: Sender type
    :param instance: Sender instance
    :param deleted: If the instance has been deleted
    :return: A list of messages generated from the instance provided
    """
    payloads: list[dict[str, Any]] = []
    if sender == MultisigConfirmation and (safe_address := instance.safe_address):
        payloads = [
            {
                # `created` is the block timestamp for on-chain approvals and the
                # confirmation creation time for off-chain signatures
                "timestamp": int(instance.created.timestamp()),
                "address": safe_address,
                "type": TransactionServiceEventType.NEW_CONFIRMATION.name,
                "owner": instance.owner,
                "safeTxHash": to_0x_hex_str(
                    HexBytes(
                        instance.multisig_transaction_hash
                        or instance.multisig_transaction_id
                    )
                ),
                "signatureType": SafeSignatureType(instance.signature_type).name,
            }
        ]
    elif sender == MultisigTransaction and deleted:
        # Off-chain event fired on post_delete: `modified` is not refreshed on delete,
        # so use the current time as the deletion (event emission) time
        payloads = [
            {
                "timestamp": int(timezone.now().timestamp()),
                "address": instance.safe,
                "type": TransactionServiceEventType.DELETED_MULTISIG_TRANSACTION.name,
                "safeTxHash": to_0x_hex_str(HexBytes(instance.safe_tx_hash)),
            }
        ]
    elif sender == MultisigTransaction:
        payload = {
            "address": instance.safe,
            #  'type': None,  It will be assigned later
            "safeTxHash": to_0x_hex_str(HexBytes(instance.safe_tx_hash)),
            "to": instance.to,
            "data": to_0x_hex_str(HexBytes(instance.data)) if instance.data else None,
        }
        if instance.executed:
            payload["type"] = (
                TransactionServiceEventType.EXECUTED_MULTISIG_TRANSACTION.name
            )
            payload["isFailed"] = instance.failed
            payload["txHash"] = to_0x_hex_str(HexBytes(instance.ethereum_tx_id))
            payload["executor"] = instance.ethereum_tx._from
        else:
            # Off-chain event (not yet executed): use the proposal creation time,
            # kept first for readability
            payload = {"timestamp": int(instance.created.timestamp()), **payload}
            payload["type"] = (
                TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name
            )
        payloads = [payload]
    elif sender == InternalTx and instance.is_ether_transfer:
        # INCOMING_ETHER / OUTGOING_ETHER
        transaction_hash = HexBytes(instance.ethereum_tx_id)
        incoming_payload = {
            "timestamp": int(instance.timestamp.timestamp()),
            "id": build_transfer_unique_id(
                transaction_hash, trace_address=instance.trace_address
            ),
            "address": instance.to,
            "type": TransactionServiceEventType.INCOMING_ETHER.name,
            "txHash": to_0x_hex_str(transaction_hash),
            "value": str(instance.value),
        }
        outgoing_payload = dict(incoming_payload)
        outgoing_payload["type"] = TransactionServiceEventType.OUTGOING_ETHER.name
        outgoing_payload["address"] = instance._from
        payloads = _filter_not_safe_transfers(
            instance, incoming_payload, outgoing_payload
        )
    elif sender in (ERC20Transfer, ERC721Transfer):
        # INCOMING_TOKEN / OUTGOING_TOKEN
        transaction_hash = HexBytes(instance.ethereum_tx_id)
        incoming_payload = {
            "timestamp": int(instance.timestamp.timestamp()),
            "id": build_transfer_unique_id(
                transaction_hash, log_index=instance.log_index
            ),
            "address": instance.to,
            "type": TransactionServiceEventType.INCOMING_TOKEN.name,
            "tokenAddress": instance.address,
            "txHash": to_0x_hex_str(transaction_hash),
            "trusted": TokenServiceProvider().is_trusted(instance.address),
        }
        if isinstance(instance, ERC20Transfer):
            incoming_payload["value"] = str(instance.value)
        else:
            incoming_payload["tokenId"] = str(instance.token_id)
        outgoing_payload = dict(incoming_payload)
        outgoing_payload["type"] = TransactionServiceEventType.OUTGOING_TOKEN.name
        outgoing_payload["address"] = instance._from
        payloads = _filter_not_safe_transfers(
            instance, incoming_payload, outgoing_payload
        )
    elif sender == SafeContract:  # Safe created
        payloads = [
            {
                "address": instance.address,
                "type": TransactionServiceEventType.SAFE_CREATED.name,
                "txHash": to_0x_hex_str(HexBytes(instance.ethereum_tx_id)),
                "blockNumber": instance.created_block_number,
            }
        ]
    elif sender == ModuleTransaction:
        # On-chain event: block timestamp is denormalized on the related InternalTx,
        # which is already dereferenced below, so no extra query is needed
        payloads = [
            {
                "timestamp": int(instance.internal_tx.timestamp.timestamp()),
                "address": instance.safe,
                "type": TransactionServiceEventType.MODULE_TRANSACTION.name,
                "module": instance.module,
                "txHash": to_0x_hex_str(HexBytes(instance.internal_tx.ethereum_tx_id)),
            }
        ]
    elif sender == SafeMessage:
        # Off-chain event: use the message creation time
        payloads = [
            {
                "timestamp": int(instance.created.timestamp()),
                "address": instance.safe,
                "type": TransactionServiceEventType.MESSAGE_CREATED.name,
                "messageHash": to_0x_hex_str(HexBytes(instance.message_hash)),
            }
        ]
    elif sender == SafeMessageConfirmation:
        # Off-chain event: use the confirmation creation time
        payloads = [
            {
                "timestamp": int(instance.created.timestamp()),
                "address": instance.safe_message.safe,  # This could make a db call
                "type": TransactionServiceEventType.MESSAGE_CONFIRMATION.name,
                "messageHash": to_0x_hex_str(HexBytes(instance.safe_message_id)),
            }
        ]

    # Add chainId to every payload
    if payloads:
        chain_id = str(get_chain_id())
        for payload in payloads:
            payload["chainId"] = chain_id

    return payloads


def filter_banned_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Exclude event payloads addressed to a banned Safe (``SafeContract.banned``),
    so no events are emitted for them. Payloads without an ``address`` (e.g.
    global delegates) are kept.

    :param payloads:
    :return: Payloads not addressed to a banned Safe
    """
    if not payloads:
        return payloads
    banned_addresses = SafeContract.objects.get_banned_addresses_cached()
    if not banned_addresses:
        return payloads
    return [
        payload
        for payload in payloads
        if payload.get("address") not in banned_addresses
    ]


def send_payloads_on_commit(payloads: list[dict[str, Any]]) -> None:
    """
    Publish the payloads when the current database transaction commits,
    excluding payloads addressed to a banned Safe. The banned set is cached
    in memory, so bans propagate within ``BANNED_SAFES_CACHE_TTL``. Payloads
    without an ``address`` are kept (e.g. delegate events not tied to a
    Safe). Every event producer must publish through here

    :param payloads:
    :return:
    """
    if payloads_to_send := filter_banned_payloads(payloads):
        get_queue_service().send_events_on_commit(payloads_to_send)


def is_relevant_event(
    sender: type[Model],
    instance: TokenTransfer | InternalTx | MultisigConfirmation | MultisigTransaction,
    created: bool,
    minutes: int = EVENT_MAX_AGE_MINUTES,
) -> bool:
    """
    For `MultisigTransaction`, event is valid if the instance was modified in the last `minutes` minutes.
    For the other instances, event is valid if the instance was created in the last `minutes` minutes.
    This time restriction is important to prevent sending duplicate transactions when reindexing.

    :param sender:
    :param instance:
    :param created:
    :param minutes: Minutes to allow an old event
    :return: `True` if event is valid, `False` otherwise
    """
    if (
        sender == MultisigTransaction
    ):  # Different logic, as `MultisigTransaction` can change from Pending to Executed
        # Don't send events for `not trusted` transactions
        if (
            not instance.trusted
            or instance.modified + timedelta(minutes=minutes) < timezone.now()
        ):
            return False
    elif not created:
        return False
    elif instance.created + timedelta(minutes=minutes) < timezone.now():
        return False
    return True


class ReorgPayload(TypedDict):
    type: str
    blockNumber: int
    chainId: str


def build_reorg_payload(block_number: int) -> ReorgPayload:
    """
    Build a reorg payload with the provided block_number and the configured chain_id.

    :param block_number:
    :return:
    """
    return ReorgPayload(
        type=TransactionServiceEventType.REORG_DETECTED.name,
        blockNumber=block_number,
        chainId=str(get_chain_id()),
    )


class DelegatePayload(TypedDict):
    type: str
    address: str | None
    delegate: str
    delegator: str
    label: str
    expiryDateSeconds: int | None
    chainId: str


def _build_delegate_payload(
    event_type: Literal[
        TransactionServiceEventType.NEW_DELEGATE,
        TransactionServiceEventType.UPDATED_DELEGATE,
        TransactionServiceEventType.DELETED_DELEGATE,
    ],
    instance: SafeContractDelegate,
) -> DelegatePayload:
    """
    Build a delegate payload with the specified event type and SafeContractDelegate instance data.

    :param event_type: The transaction event type, restricted to NEW_DELEGATE, UPDATED_DELEGATE, or DELETED_DELEGATE.
    :param instance: An instance of SafeContractDelegate.
    :return: A DelegatePayload dictionary with details about the delegate.
    """
    return DelegatePayload(
        type=event_type.name,
        address=instance.safe_contract_id if instance.safe_contract_id else None,
        delegate=instance.delegate,
        delegator=instance.delegator,
        label=instance.label,
        expiryDateSeconds=(
            int(instance.expiry_date.timestamp()) if instance.expiry_date else None
        ),
        chainId=str(get_chain_id()),
    )


def build_save_delegate_payload(
    instance: SafeContractDelegate, created: bool = True
) -> DelegatePayload:
    if created:
        event_type = TransactionServiceEventType.NEW_DELEGATE
    else:
        event_type = TransactionServiceEventType.UPDATED_DELEGATE
    return _build_delegate_payload(event_type, instance)


def build_delete_delegate_payload(instance: SafeContractDelegate) -> DelegatePayload:
    return _build_delegate_payload(
        TransactionServiceEventType.DELETED_DELEGATE, instance
    )


# Decoded Safe functions that can change the Safe configuration. The configuration
# set by `setup` is notified with `SAFE_CREATED`
SAFE_CONFIG_FUNCTIONS = frozenset(
    {
        "addOwnerWithThreshold",
        "removeOwner",
        "removeOwnerWithThreshold",
        "swapOwner",
        "changeThreshold",
        "changeMasterCopy",
        "setFallbackHandler",
        "setGuard",
        "setModuleGuard",
        "enableModule",
        "disableModule",
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class SafeConfigSnapshot:
    """
    Copy of the configuration fields of a ``SafeLastStatus``. The lists are
    copied, as the processor keeps mutating the same ``SafeLastStatus`` instance
    for the next decoded txs of the batch.
    """

    owners: list[ChecksumAddress]
    threshold: int
    nonce: int
    master_copy: ChecksumAddress
    fallback_handler: ChecksumAddress
    guard: ChecksumAddress
    module_guard: ChecksumAddress
    enabled_modules: list[ChecksumAddress]

    @classmethod
    def from_safe_status(cls, safe_status: SafeLastStatus) -> "SafeConfigSnapshot":
        return cls(
            owners=list(safe_status.owners),
            threshold=safe_status.threshold,
            nonce=safe_status.nonce,
            master_copy=safe_status.master_copy,
            fallback_handler=safe_status.fallback_handler,
            guard=safe_status.guard or NULL_ADDRESS,
            module_guard=safe_status.module_guard or NULL_ADDRESS,
            enabled_modules=list(safe_status.enabled_modules),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "owners": self.owners,
            "threshold": self.threshold,
            "nonce": self.nonce,
            "enabledModules": self.enabled_modules,
            "guard": self.guard,
            "moduleGuard": self.module_guard,
            "fallbackHandler": self.fallback_handler,
            "masterCopy": self.master_copy,
        }


def take_safe_config_snapshot(
    function_name: str,
    internal_tx: InternalTx,
    safe_status: SafeLastStatus | None,
) -> SafeConfigSnapshot | None:
    """
    Take the configuration of the Safe before processing a decoded tx, to build
    its ``SAFE_CONFIG_UPDATED`` payloads after with ``build_safe_config_payloads``.
    The age is checked with the block timestamp, the same as ``MODULE_TRANSACTION``
    events.

    :param function_name: Decoded function about to be processed
    :param internal_tx: Internal tx about to be processed
    :param safe_status: Safe status before processing the decoded tx
    :return: Snapshot, or ``None`` if no event must be sent for the decoded tx
    """
    if (
        function_name not in SAFE_CONFIG_FUNCTIONS
        or safe_status is None
        or settings.DISABLE_SERVICE_EVENTS
        or internal_tx.timestamp + EVENT_MAX_AGE < timezone.now()
    ):
        return None
    return SafeConfigSnapshot.from_safe_status(safe_status)


def build_safe_config_payloads(
    before: SafeConfigSnapshot,
    internal_tx: InternalTx,
    safe_status: SafeLastStatus,
) -> list[dict[str, Any]]:
    """
    Build one ``SAFE_CONFIG_UPDATED`` payload per configuration change made by a
    decoded tx, following the Safe contract events: a swapped owner is a removed
    owner plus an added owner, and the threshold is only reported when its value
    changes.

    :param before: Snapshot returned by ``take_safe_config_snapshot``
    :param internal_tx: Processed internal tx
    :param safe_status: Safe status after processing the decoded tx
    :return: Payloads, empty if nothing changed
    """
    after = SafeConfigSnapshot.from_safe_status(safe_status)
    changes: list[tuple[str, dict[str, Any]]] = []
    changes.extend(
        ("REMOVED_OWNER", {"owner": owner})
        for owner in before.owners
        if owner not in after.owners
    )
    changes.extend(
        ("ADDED_OWNER", {"owner": owner})
        for owner in after.owners
        if owner not in before.owners
    )
    if before.threshold != after.threshold:
        changes.append(("CHANGED_THRESHOLD", {"threshold": after.threshold}))
    changes.extend(
        ("DISABLED_MODULE", {"module": module})
        for module in before.enabled_modules
        if module not in after.enabled_modules
    )
    changes.extend(
        ("ENABLED_MODULE", {"module": module})
        for module in after.enabled_modules
        if module not in before.enabled_modules
    )
    if before.guard != after.guard:
        changes.append(("CHANGED_GUARD", {"guard": after.guard}))
    if before.module_guard != after.module_guard:
        changes.append(("CHANGED_MODULE_GUARD", {"moduleGuard": after.module_guard}))
    if before.fallback_handler != after.fallback_handler:
        changes.append(
            ("CHANGED_FALLBACK_HANDLER", {"fallbackHandler": after.fallback_handler})
        )
    if before.master_copy != after.master_copy:
        changes.append(("CHANGED_MASTER_COPY", {"masterCopy": after.master_copy}))

    if not changes:
        return []

    timestamp = int(internal_tx.timestamp.timestamp())
    tx_hash = to_0x_hex_str(HexBytes(internal_tx.ethereum_tx_id))
    status = after.to_payload()
    chain_id = str(get_chain_id())
    return [
        {
            "timestamp": timestamp,
            "address": safe_status.address,
            "type": TransactionServiceEventType.SAFE_CONFIG_UPDATED.name,
            "txHash": tx_hash,
            "change": change,
            "data": data,
            "status": status,
            "chainId": chain_id,
        }
        for change, data in changes
    ]
