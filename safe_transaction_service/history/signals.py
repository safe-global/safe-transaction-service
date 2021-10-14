import json
from datetime import timedelta
from typing import Any, Dict, List, Type, Union

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from hexbytes import HexBytes

from safe_transaction_service.notifications.tasks import send_notification_task
from safe_transaction_service.utils.ethereum import get_ethereum_network

from .models import (
    EthereumEvent,
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    WebHookType,
)
from .tasks import send_webhook_task


@receiver(
    post_save,
    sender=MultisigConfirmation,
    dispatch_uid="multisig_confirmation.bind_confirmation",
)
@receiver(
    post_save,
    sender=MultisigTransaction,
    dispatch_uid="multisig_transaction.bind_confirmation",
)
def bind_confirmation(
    sender: Type[Model],
    instance: Union[MultisigConfirmation, MultisigTransaction],
    created: bool,
    **kwargs,
) -> None:
    """
    When a `MultisigConfirmation` is saved, it tries to bind it to an existing `MultisigTransaction`, and the opposite.
    :param sender: Could be MultisigConfirmation or MultisigTransaction
    :param instance: Instance of MultisigConfirmation or `MultisigTransaction`
    :param created: `True` if model has just been created, `False` otherwise
    :param kwargs:
    :return:
    """
    if not created:
        return

    if sender == MultisigTransaction:
        updated = (
            MultisigConfirmation.objects.without_transaction()
            .filter(multisig_transaction_hash=instance.safe_tx_hash)
            .update(multisig_transaction=instance)
        )
        if updated:
            # Update modified on MultisigTransaction if at least one confirmation is added. Tx will now be trusted
            instance.modified = timezone.now()
            instance.trusted = True
            instance.save(update_fields=["modified", "trusted"])
    elif sender == MultisigConfirmation:
        if instance.multisig_transaction_id:
            # Update modified on MultisigTransaction if one confirmation is added. Tx will now be trusted
            MultisigTransaction.objects.filter(
                safe_tx_hash=instance.multisig_transaction_hash
            ).update(modified=instance.created, trusted=True)
        else:
            try:
                if instance.multisig_transaction_hash:
                    multisig_transaction = MultisigTransaction.objects.get(
                        safe_tx_hash=instance.multisig_transaction_hash
                    )
                    multisig_transaction.modified = instance.created
                    multisig_transaction.trusted = True
                    multisig_transaction.save(update_fields=["modified", "trusted"])

                    instance.multisig_transaction = multisig_transaction
                    instance.save(update_fields=["multisig_transaction"])
            except MultisigTransaction.DoesNotExist:
                pass


def build_webhook_payload(
    sender: Type[Model],
    instance: Union[
        EthereumEvent, InternalTx, MultisigConfirmation, MultisigTransaction
    ],
) -> List[Dict[str, Any]]:
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
    elif (
        sender == EthereumEvent
        and "to" in instance.arguments
        and "from" in instance.arguments
    ):
        # INCOMING_TOKEN / OUTGOING_TOKEN
        incoming_payload = {
            "address": instance.arguments["to"],
            "type": WebHookType.INCOMING_TOKEN.name,
            "tokenAddress": instance.address,
            "txHash": HexBytes(instance.ethereum_tx_id).hex(),
        }
        for element in ("tokenId", "value"):
            if element in instance.arguments:
                incoming_payload[element] = str(instance.arguments[element])
        outgoing_payload = dict(incoming_payload)
        outgoing_payload["type"] = WebHookType.OUTGOING_TOKEN.name
        outgoing_payload["address"] = instance.arguments["from"]
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
                "module": instance.module,
                "type": WebHookType.MODULE_TRANSACTION.name,
                "txHash": HexBytes(instance.internal_tx.ethereum_tx_id).hex(),
            }
        ]

    # Add chainId to every payload
    for payload in payloads:
        payload["chainId"] = str(get_ethereum_network().value)

    return payloads


def is_valid_webhook(
    sender: Type[Model],
    instance: Union[
        EthereumEvent, InternalTx, MultisigConfirmation, MultisigTransaction
    ],
    created: bool,
    minutes: int = 10,
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
        if instance.modified + timedelta(minutes=minutes) < timezone.now():
            return False
    elif not created:
        return False
    elif instance.created + timedelta(minutes=minutes) < timezone.now():
        return False
    return True


@receiver(
    post_save,
    sender=ModuleTransaction,
    dispatch_uid="module_transaction.process_webhook",
)
@receiver(
    post_save,
    sender=MultisigConfirmation,
    dispatch_uid="multisig_confirmation.process_webhook",
)
@receiver(
    post_save,
    sender=MultisigTransaction,
    dispatch_uid="multisig_transaction.process_webhook",
)
@receiver(
    post_save, sender=EthereumEvent, dispatch_uid="ethereum_event.process_webhook"
)
@receiver(post_save, sender=InternalTx, dispatch_uid="internal_tx.process_webhook")
@receiver(post_save, sender=SafeContract, dispatch_uid="safe_contract.process_webhook")
def process_webhook(
    sender: Type[Model],
    instance: Union[
        EthereumEvent,
        InternalTx,
        MultisigConfirmation,
        MultisigTransaction,
        SafeContract,
    ],
    created: bool,
    **kwargs,
) -> None:
    if is_valid_webhook(sender, instance, created):
        # Don't send information for older than 10 minutes transactions
        # This triggers a DB query on EthereumEvent, InternalTx (they are not TimeStampedModel)
        payloads = build_webhook_payload(sender, instance)
        for payload in payloads:
            if address := payload.get("address"):
                send_webhook_task.delay(address, payload)
                send_notification_task.apply_async(args=(address, payload), countdown=5)
