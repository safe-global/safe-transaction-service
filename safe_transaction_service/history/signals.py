from logging import getLogger
from typing import Type, Union

from django.conf import settings
from django.db.models import Model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from ..events.services.queue_service import get_queue_service
from .cache import remove_cache_view_by_instance
from .models import (
    ERC20Transfer,
    ERC721Transfer,
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
    SafeLastStatus,
    SafeMasterCopy,
    SafeStatus,
    TokenTransfer,
)
from .services.event_service import (
    build_delete_delegate_payload,
    build_event_payload,
    build_save_delegate_payload,
    is_relevant_event,
)

logger = getLogger(__name__)


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
        return None

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


@receiver(
    post_save,
    sender=SafeMasterCopy,
    dispatch_uid="safe_master_copy.clear_version_cache",
)
def safe_master_copy_clear_cache(
    sender: Type[Model],
    instance: Union[MultisigConfirmation, MultisigTransaction],
    created: bool,
    **kwargs,
) -> None:
    """
    Clear SafeMasterCopy cache if something is modified

    :param sender:
    :param instance:
    :param created:
    :param kwargs:
    :return:
    """
    SafeMasterCopy.objects.get_version_for_address.cache_clear()


def _process_event(
    sender: Type[Model],
    instance: Union[
        TokenTransfer,
        InternalTx,
        MultisigConfirmation,
        MultisigTransaction,
        SafeContract,
    ],
    created: bool,
    deleted: bool,
) -> None:
    """
    Process models and
    :param sender:
    :param instance:
    :param created:
    :param deleted:
    :return:
    """
    if settings.DISABLE_SERVICE_EVENTS:
        return None

    assert not (
        created and deleted
    ), "An instance cannot be created and deleted at the same time"

    logger.debug("Removing cache for object=%s", instance)
    remove_cache_view_by_instance(instance)
    logger.debug("Start building payloads for created=%s object=%s", created, instance)
    payloads = build_event_payload(sender, instance, deleted=deleted)
    logger.debug(
        "End building payloads %s for created=%s object=%s", payloads, created, instance
    )
    for payload in payloads:
        if address := payload.get("address"):
            if is_relevant_event(sender, instance, created):
                logger.debug(
                    "[%s] Triggering send_event tasks for created=%s object=%s",
                    address,
                    created,
                    instance,
                )
                queue_service = get_queue_service()
                queue_service.send_event(payload)
            else:
                logger.debug(
                    "[%s] Event will not be sent for created=%s object=%s",
                    address,
                    created,
                    instance,
                )


@receiver(
    post_save,
    sender=ModuleTransaction,
    dispatch_uid="module_transaction.process_event",
)
@receiver(
    post_save,
    sender=MultisigConfirmation,
    dispatch_uid="multisig_confirmation.process_event",
)
@receiver(
    post_save,
    sender=MultisigTransaction,
    dispatch_uid="multisig_transaction.process_event",
)
@receiver(
    post_save,
    sender=ERC20Transfer,
    dispatch_uid="erc20_transfer.process_event",
)
@receiver(
    post_save,
    sender=ERC721Transfer,
    dispatch_uid="erc721_transfer.process_event",
)
@receiver(post_save, sender=InternalTx, dispatch_uid="internal_tx.process_event")
@receiver(
    post_save,
    sender=SafeContract,
    dispatch_uid="safe_contract.process_event",
)
def process_event(
    sender: Type[Model],
    instance: Union[
        TokenTransfer,
        InternalTx,
        MultisigConfirmation,
        MultisigTransaction,
        SafeContract,
    ],
    created: bool,
    **kwargs,
) -> None:
    return _process_event(sender, instance, created, False)


@receiver(
    post_delete,
    sender=MultisigTransaction,
    dispatch_uid="multisig_transaction.process_delete_multisig_transaction_event",
)
def process_delete_multisig_transaction_event(
    sender: Type[Model], instance: MultisigTransaction, *args, **kwargs
):
    return _process_event(sender, instance, False, True)


@receiver(
    post_save,
    sender=SafeLastStatus,
    dispatch_uid="safe_last_status.add_to_historical_table",
)
def add_to_historical_table(
    sender: Type[Model],
    instance: SafeLastStatus,
    created: bool,
    **kwargs,
) -> SafeStatus:
    """
    Add every `SafeLastStatus` entry to `SafeStatus` historical table

    :param sender:
    :param instance:
    :param created:
    :param kwargs:
    :return: SafeStatus
    """
    logger.debug(
        "Storing created=%s object=%s on `SafeStatus` table",
        created,
        instance,
    )
    safe_status = SafeStatus.from_status_instance(instance)
    safe_status.save()
    return safe_status


@receiver(
    post_save,
    sender=SafeContractDelegate,
    dispatch_uid="safe_contract_delegate.process_save_delegate_user_event",
)
def process_save_delegate_user_event(
    sender: Type[Model],
    instance: SafeContractDelegate,
    created: bool,
    **kwargs,
):
    payload_event = build_save_delegate_payload(instance, created)
    queue_service = get_queue_service()
    queue_service.send_event(payload_event)


@receiver(
    post_delete,
    sender=SafeContractDelegate,
    dispatch_uid="safe_contract_delegate.process_delete_delegate_user_event",
)
def process_delete_delegate_user_event(
    sender: Type[Model], instance: SafeContractDelegate, *args, **kwargs
):
    payload_event = build_delete_delegate_payload(instance)
    queue_service = get_queue_service()
    queue_service.send_event(payload_event)
