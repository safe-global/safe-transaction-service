import json
from datetime import timedelta
from typing import Any, Dict, List, Type, Union

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
    TokenTransfer,
    WebHookType,
)
from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.utils.ethereum import get_chain_id


def build_webhook_payload(
    sender: Type[Model],
    instance: Union[
        TokenTransfer, InternalTx, MultisigConfirmation, MultisigTransaction
    ],
    deleted: bool = False,
) -> List[Dict[str, Any]]:
    """
    :param sender: Sender type
    :param instance: Sender instance
    :param deleted: If the instance has been deleted
    :return: A list of webhooks generated from the instance provided
    """
    payloads: List[Dict[str, Any]] = []
    if sender == MultisigConfirmation and instance.multisig_transaction_id:
        payloads = [
            {
                "address": instance.multisig_transaction.safe,  # This could make a db call
                "type": WebHookType.NEW_CONFIRMATION.name,
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
                "type": WebHookType.DELETED_MULTISIG_TRANSACTION.name,
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
            payload["type"] = WebHookType.EXECUTED_MULTISIG_TRANSACTION.name
            payload["failed"] = json.dumps(
                instance.failed
            )  # Firebase only accepts strings
            payload["txHash"] = HexBytes(instance.ethereum_tx_id).hex()
        else:
            payload["type"] = WebHookType.PENDING_MULTISIG_TRANSACTION.name
        payloads = [payload]
    elif sender == InternalTx and instance.is_ether_transfer:  # INCOMING_ETHER
        incoming_payload = {
            "address": instance.to,
            "type": WebHookType.INCOMING_ETHER.name,
            "txHash": HexBytes(instance.ethereum_tx_id).hex(),
            "value": str(instance.value),
        }
        outgoing_payload = dict(incoming_payload)
        outgoing_payload["type"] = WebHookType.OUTGOING_ETHER.name
        outgoing_payload["address"] = instance._from
        payloads = [incoming_payload, outgoing_payload]
    elif sender in (ERC20Transfer, ERC721Transfer):
        # INCOMING_TOKEN / OUTGOING_TOKEN
        incoming_payload = {
            "address": instance.to,
            "type": WebHookType.INCOMING_TOKEN.name,
            "tokenAddress": instance.address,
            "txHash": HexBytes(instance.ethereum_tx_id).hex(),
        }
        if isinstance(instance, ERC20Transfer):
            incoming_payload["value"] = str(instance.value)
        else:
            incoming_payload["tokenId"] = str(instance.token_id)
        outgoing_payload = dict(incoming_payload)
        outgoing_payload["type"] = WebHookType.OUTGOING_TOKEN.name
        outgoing_payload["address"] = instance._from
        payloads = [incoming_payload, outgoing_payload]
    elif sender == SafeContract:  # Safe created
        payloads = [
            {
                "address": instance.address,
                "type": WebHookType.SAFE_CREATED.name,
                "txHash": HexBytes(instance.ethereum_tx_id).hex(),
                "blockNumber": instance.created_block_number,
            }
        ]
    elif sender == ModuleTransaction:
        payloads = [
            {
                "address": instance.safe,
                "type": WebHookType.MODULE_TRANSACTION.name,
                "module": instance.module,
                "txHash": HexBytes(instance.internal_tx.ethereum_tx_id).hex(),
            }
        ]
    elif sender == SafeMessage:
        payloads = [
            {
                "address": instance.safe,
                "type": WebHookType.MESSAGE_CREATED.name,
                "messageHash": HexBytes(instance.message_hash).hex(),
            }
        ]
    elif sender == SafeMessageConfirmation:
        payloads = [
            {
                "address": instance.safe_message.safe,  # This could make a db call
                "type": WebHookType.MESSAGE_CONFIRMATION.name,
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
    For `MultisigTransaction`, webhook is valid if the instance was modified in the last `minutes` minutes.
    For the other instances, webhook is valid if the instance was created in the last `minutes` minutes.
    This time restriction is important to prevent sending duplicate transactions when reindexing.

    :param sender:
    :param instance:
    :param created:
    :param minutes: Minutes to allow a old notification
    :return: `True` if webhook is valid, `False` otherwise
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
