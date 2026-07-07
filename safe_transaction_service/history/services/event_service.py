# SPDX-License-Identifier: FSL-1.1-MIT
"""
Build event payloads for the queue
"""

import json
from datetime import timedelta
from logging import getLogger
from typing import Any, Literal, TypedDict

from django.db.models import Model
from django.utils import timezone

from hexbytes import HexBytes
from safe_eth.util.util import to_0x_hex_str

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


def _get_safe_threshold(safe_address: str) -> int | None:
    """
    Current threshold of the Safe from ``SafeLastStatus``. Safe messages are not tied
    to a nonce, so using the last known threshold value.

    :param safe_address:
    :return: Threshold, or `None` if the Safe has no indexed status yet
    """
    return (
        SafeLastStatus.objects.filter(address=safe_address)
        .values_list("threshold", flat=True)
        .first()
    )


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
    if sender == MultisigConfirmation and instance.multisig_transaction_id:
        # Off-chain event: use the confirmation creation time
        payloads = [
            {
                "timestamp": int(instance.created.timestamp()),
                "address": instance.multisig_transaction.safe,  # This could make a db call
                "type": TransactionServiceEventType.NEW_CONFIRMATION.name,
                "owner": instance.owner,
                "safeTxHash": to_0x_hex_str(HexBytes(instance.multisig_transaction_id)),
                "confirmationsRequired": instance.multisig_transaction.get_confirmations_required(),
                "confirmationsCount": instance.multisig_transaction.confirmations.count(),
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
            # Deprecated: stringified boolean kept for legacy clients, use `isFailed` instead
            payload["failed"] = json.dumps(instance.failed)
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
                "threshold": _get_safe_threshold(instance.safe),
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
                "threshold": _get_safe_threshold(instance.safe_message.safe),
                "owner": instance.owner,
            }
        ]

    # Add chainId to every payload
    if payloads:
        chain_id = str(get_chain_id())
        for payload in payloads:
            payload["chainId"] = chain_id

    return payloads


def is_relevant_event(
    sender: type[Model],
    instance: TokenTransfer | InternalTx | MultisigConfirmation | MultisigTransaction,
    created: bool,
    minutes: int = 60,
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
