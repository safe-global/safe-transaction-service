from typing import Any, Dict, Optional, Type, Union

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from hexbytes import HexBytes

from .models import (EthereumEvent, InternalTx, MultisigConfirmation,
                     MultisigTransaction, WebHookType)
from .tasks import send_webhook_task


@receiver(post_save, sender=MultisigConfirmation, dispatch_uid='multisig_confirmation.bind_confirmation')
@receiver(post_save, sender=MultisigTransaction, dispatch_uid='multisig_transaction.bind_confirmation')
def bind_confirmation(sender: Type[Model],
                      instance: Union[MultisigConfirmation, MultisigTransaction],
                      created: bool, **kwargs) -> None:
    """
    When a `MultisigConfirmation` is saved, it tries to bind it to an existing `MultisigTransaction`, and the opposite.
    :param sender: Could be MultisigConfirmation or MultisigTransaction
    :param instance: Instance of MultisigConfirmation or `MultisigTransaction`
    :param created: True if model has just been created, `False` otherwise
    :param kwargs:
    :return:
    """
    if not created:
        return

    if sender == MultisigTransaction:
        updated = MultisigConfirmation.objects.without_transaction().filter(
            multisig_transaction_hash=instance.safe_tx_hash
        ).update(
            multisig_transaction=instance
        )
        if updated:
            # Update modified on MultisigTransaction if at least one confirmation is added
            # Tx will now be trusted
            instance.modified = timezone.now()
            instance.trusted = True
            instance.save(update_fields=['modified', 'trusted'])
    elif sender == MultisigConfirmation:
        if not instance.multisig_transaction_id:
            try:
                if instance.multisig_transaction_hash:
                    multisig_transaction = MultisigTransaction.objects.get(
                        safe_tx_hash=instance.multisig_transaction_hash)
                    multisig_transaction.modified = timezone.now()
                    multisig_transaction.trusted = True
                    multisig_transaction.save(update_fields=['modified', 'trusted'])

                    instance.multisig_transaction = multisig_transaction
                    instance.save(update_fields=['multisig_transaction'])
            except MultisigTransaction.DoesNotExist:
                pass


@receiver(post_save, sender=MultisigConfirmation, dispatch_uid='multisig_confirmation.send_webhook')
@receiver(post_save, sender=MultisigTransaction, dispatch_uid='multisig_transaction.send_webhook')
@receiver(post_save, sender=EthereumEvent, dispatch_uid='multisig_transaction.ethereum_event')
@receiver(post_save, sender=InternalTx, dispatch_uid='multisig_transaction.internal_tx')
def send_webhook(sender: Type[Model],
                 instance: Union[MultisigConfirmation, MultisigTransaction],
                 created: bool, **kwargs) -> None:

    address: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

    if not created:
        return

    if sender == MultisigConfirmation and instance.multisig_transaction_id:
        address = instance.multisig_transaction.safe  # This is making a db call
        payload = {
            'address': address,
            'type': WebHookType.NEW_CONFIRMATION.name,
            'owner': instance.owner,
            'safeTxHash': HexBytes(instance.multisig_transaction.safe_tx_hash).hex()
        }
    elif sender == MultisigTransaction:
        address = instance.safe
        payload = {
            'address': address,
            'type': None,
            'safeTxHash': HexBytes(instance.safe_tx_hash).hex()
        }
        if instance.executed:
            payload['type'] = WebHookType.EXECUTED_MULTISIG_TRANSACTION.name
            payload['txHash'] = HexBytes(instance.ethereum_tx_id).hex()
        else:
            payload['type'] = WebHookType.PENDING_MULTISIG_TRANSACTION.name
    elif sender == InternalTx and instance.is_ether_transfer:  # INCOMING_ETHER
        address = instance.to
        payload = {
            'address': address,
            'type': WebHookType.INCOMING_ETHER.name,
            'txHash': HexBytes(instance.ethereum_tx_id).hex(),
            'value': str(instance.value),
        }
    elif sender == EthereumEvent and 'to' in instance.arguments:  # INCOMING_TOKEN
        address = instance.arguments['to']
        payload = {
            'address': address,
            'type': WebHookType.INCOMING_TOKEN.name,
            'tokenAddress': instance.address,
            'txHash': HexBytes(instance.ethereum_tx_id).hex(),
        }
        for element in ('tokenId', 'value'):
            if element in instance.arguments:
                payload[element] = str(instance.arguments[element])

    if address and payload:
        send_webhook_task.delay(address, payload)


@receiver(post_save, sender=MultisigConfirmation, dispatch_uid='multisig_confirmation.send_webhook')
@receiver(post_save, sender=MultisigTransaction, dispatch_uid='multisig_transaction.send_webhook')
@receiver(post_save, sender=EthereumEvent, dispatch_uid='multisig_transaction.ethereum_event')
@receiver(post_save, sender=InternalTx, dispatch_uid='multisig_transaction.internal_tx')
def send_notification(sender: Type[Model],
                      instance: Union[MultisigConfirmation, MultisigTransaction],
                      created: bool, **kwargs) -> None:

    address: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

    if not created:
        return

    if sender == MultisigConfirmation and instance.multisig_transaction_id:
        address = instance.multisig_transaction.safe  # This is making a db call
        payload = {
            'address': address,
            'type': WebHookType.NEW_CONFIRMATION.name,
            'owner': instance.owner,
            'safeTxHash': HexBytes(instance.multisig_transaction.safe_tx_hash).hex()
        }
    elif sender == MultisigTransaction:
        address = instance.safe
        payload = {
            'address': address,
            'type': None,
            'safeTxHash': HexBytes(instance.safe_tx_hash).hex()
        }
        if instance.executed:
            payload['type'] = WebHookType.EXECUTED_MULTISIG_TRANSACTION.name
            payload['txHash'] = HexBytes(instance.ethereum_tx_id).hex()
        else:
            payload['type'] = WebHookType.PENDING_MULTISIG_TRANSACTION.name
    elif sender == InternalTx and instance.is_ether_transfer:  # INCOMING_ETHER
        address = instance.to
        payload = {
            'address': address,
            'type': WebHookType.INCOMING_ETHER.name,
            'txHash': HexBytes(instance.ethereum_tx_id).hex(),
            'value': str(instance.value),
        }
    elif sender == EthereumEvent and 'to' in instance.arguments:  # INCOMING_TOKEN
        address = instance.arguments['to']
        payload = {
            'address': address,
            'type': WebHookType.INCOMING_TOKEN.name,
            'tokenAddress': instance.address,
            'txHash': HexBytes(instance.ethereum_tx_id).hex(),
        }
        for element in ('tokenId', 'value'):
            if element in instance.arguments:
                payload[element] = str(instance.arguments[element])

    if address and payload:
        send_webhook_task.delay(address, payload)

