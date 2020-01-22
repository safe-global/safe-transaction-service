from typing import Any, Dict, Optional, Type, Union

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from hexbytes import HexBytes

from .models import MultisigConfirmation, MultisigTransaction, SafeContract
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
        for multisig_confirmation in MultisigConfirmation.objects.without_transaction().filter(
                multisig_transaction_hash=instance.safe_tx_hash):
            multisig_confirmation.multisig_transaction = instance
            multisig_confirmation.save(update_fields=['multisig_transaction'])
    elif sender == MultisigConfirmation:
        if not instance.multisig_transaction_id:
            try:
                if instance.multisig_transaction_hash:
                    instance.multisig_transaction = MultisigTransaction.objects.get(
                        safe_tx_hash=instance.multisig_transaction_hash)
                    instance.save(update_fields=['multisig_transaction'])
            except MultisigTransaction.DoesNotExist:
                pass


@receiver(post_save, sender=SafeContract, dispatch_uid='safe_contract.fix_erc20_block_number')
def fix_erc20_block_number(sender: Type[Model], instance: SafeContract, created: bool, **kwargs) -> None:
    """
    When a `SafeContract` is saved, sets the `erc20_block_number` if not set
    :param sender: SafeContract
    :param instance: Instance of SafeContract
    :param created: True if model has just been created, `False` otherwise
    :param kwargs:
    :return:
    """
    if not created:
        return
    if sender == SafeContract:
        if instance.erc20_block_number == 0:
            if instance.ethereum_tx and instance.ethereum_tx.block_id:  # EthereumTx is mandatory, block is not
                instance.erc20_block_number = instance.ethereum_tx.block_id
                instance.save()


@receiver(post_save, sender=MultisigConfirmation, dispatch_uid='multisig_confirmation.send_webhook')
@receiver(post_save, sender=MultisigTransaction, dispatch_uid='multisig_transaction.send_webhook')
def send_webhook(sender: Type[Model],
                 instance: Union[MultisigConfirmation, MultisigTransaction],
                 created: bool, **kwargs) -> None:

    address: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

    if sender == MultisigConfirmation and instance.multisig_transaction_id:
        address = instance.multisig_transaction.safe
        payload = {
            'type': 'NEW_CONFIRMATION',
            'owner': instance.owner,
            'safeTxHash': HexBytes(instance.multisig_transaction.safe_tx_hash).hex()
        }
    elif sender == MultisigTransaction:
        address = instance.safe
        payload = {
            'safeTxHash': HexBytes(instance.safe_tx_hash).hex()
        }
        if instance.executed:
            payload['type'] = 'EXECUTED_MULTISIG_TRANSACTION'
            payload['txHash'] = HexBytes(instance.ethereum_tx_id).hex()
        else:
            payload['type'] = 'PENDING_MULTISIG_TRANSACTION'
    # else:
        # INCOMING_ETHER or INCOMING_TOKEN

    if address and payload:
        send_webhook_task.delay(address, payload)
