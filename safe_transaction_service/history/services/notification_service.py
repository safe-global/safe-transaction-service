import json
from datetime import timedelta
from typing import Any, Dict, List, Optional, Type, TypedDict, Union

from django.db.models import Model
from django.utils import timezone

from hexbytes import HexBytes

from safe_transaction_service.history.models import (
    ERC20Transfer,
    ERC721Transfer,
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
    TokenTransfer,
    TransactionServiceEventType,
)
from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.utils.ethereum import get_chain_id


def build_event_payload(
    sender: Type[Model],
    instance: Union[
        TokenTransfer,
        InternalTx,
        MultisigConfirmation,
        MultisigTransaction,
        SafeMessage,
        SafeMessageConfirmation,
    ],
    deleted: bool = False,
) -> List[Dict[str, Any]]:
    """
    :param sender: Sender type
    :param instance: Sender instance
    :param deleted: If the instance has been deleted
    :return: A list of messages generated from the instance provided
    """
    payloads: List[Dict[str, Any]] = []
    if sender == MultisigConfirmation and instance.multisig_transaction_id:
        payloads = [
            {
                "address": instance.multisig_transaction.safe,  # This could make a db call
                "type": TransactionServiceEventType.NEW_CONFIRMATION.name,
                "owner": instance.owner,
                "safeTxHash": HexBytes(
                    instance.multisig_transaction.safe_tx_hash
                ).hex(),
            }
        ]
    elif sender == MultisigTransaction and deleted:
        payloads = [
            {
                "address": instance.safe,
                "type": TransactionServiceEventType.DELETED_MULTISIG_TRANSACTION.name,
                "safeTxHash": HexBytes(instance.safe_tx_hash).hex(),
            }
        ]
    elif sender == MultisigTransaction:
        payload = {
            "address": instance.safe,
            #  'type': None,  It will be assigned later
            "safeTxHash": HexBytes(instance.safe_tx_hash).hex(),
        }
        if instance.executed:
            payload["type"] = (
                TransactionServiceEventType.EXECUTED_MULTISIG_TRANSACTION.name
            )
            payload["failed"] = json.dumps(
                instance.failed
            )  # Firebase only accepts strings
            payload["txHash"] = HexBytes(instance.ethereum_tx_id).hex()
        else:
            payload["type"] = (
                TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name
            )
        payloads = [payload]
    elif sender == InternalTx and instance.is_ether_transfer:  # INCOMING_ETHER
        incoming_payload = {
            "address": instance.to,
            "type": TransactionServiceEventType.INCOMING_ETHER.name,
            "txHash": HexBytes(instance.ethereum_tx_id).hex(),
            "value": str(instance.value),
        }
        outgoing_payload = dict(incoming_payload)
        outgoing_payload["type"] = TransactionServiceEventType.OUTGOING_ETHER.name
        outgoing_payload["address"] = instance._from
        payloads = [incoming_payload, outgoing_payload]
    elif sender in (ERC20Transfer, ERC721Transfer):
        # INCOMING_TOKEN / OUTGOING_TOKEN
        incoming_payload = {
            "address": instance.to,
            "type": TransactionServiceEventType.INCOMING_TOKEN.name,
            "tokenAddress": instance.address,
            "txHash": HexBytes(instance.ethereum_tx_id).hex(),
        }
        if isinstance(instance, ERC20Transfer):
            incoming_payload["value"] = str(instance.value)
        else:
            incoming_payload["tokenId"] = str(instance.token_id)
        outgoing_payload = dict(incoming_payload)
        outgoing_payload["type"] = TransactionServiceEventType.OUTGOING_TOKEN.name
        outgoing_payload["address"] = instance._from
        payloads = [incoming_payload, outgoing_payload]
    elif sender == SafeContract:  # Safe created
        payloads = [
            {
                "address": instance.address,
                "type": TransactionServiceEventType.SAFE_CREATED.name,
                "txHash": HexBytes(instance.ethereum_tx_id).hex(),
                "blockNumber": instance.created_block_number,
            }
        ]
    elif sender == ModuleTransaction:
        payloads = [
            {
                "address": instance.safe,
                "type": TransactionServiceEventType.MODULE_TRANSACTION.name,
                "module": instance.module,
                "txHash": HexBytes(instance.internal_tx.ethereum_tx_id).hex(),
            }
        ]
    elif sender == SafeMessage:
        payloads = [
            {
                "address": instance.safe,
                "type": TransactionServiceEventType.MESSAGE_CREATED.name,
                "messageHash": HexBytes(instance.message_hash).hex(),
            }
        ]
    elif sender == SafeMessageConfirmation:
        payloads = [
            {
                "address": instance.safe_message.safe,  # This could make a db call
                "type": TransactionServiceEventType.MESSAGE_CONFIRMATION.name,
                "messageHash": HexBytes(instance.safe_message.message_hash).hex(),
            }
        ]

    # Add chainId to every payload
    for payload in payloads:
        payload["chainId"] = str(get_chain_id())

    return payloads


def is_relevant_notification(
    sender: Type[Model],
    instance: Union[
        TokenTransfer, InternalTx, MultisigConfirmation, MultisigTransaction
    ],
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
    :param minutes: Minutes to allow a old notification
    :return: `True` if event is valid, `False` otherwise
    """
    if (
        sender == MultisigTransaction
    ):  # Different logic, as `MultisigTransaction` can change from Pending to Executed
        # Don't send notifications for `not trusted` transactions
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
    address: Optional[str]
    delegate: str
    delegator: str
    label: str
    expiryDateSeconds: Optional[int]
    chainId: str


def _build_delegate_payload(
    event_type: Union[
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
