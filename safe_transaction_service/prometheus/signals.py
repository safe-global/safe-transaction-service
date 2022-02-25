from typing import Type

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from safe_transaction_service.history.models import MultisigTransaction

from .metrics import get_metrics


@receiver(
    post_save,
    sender=MultisigTransaction,
    dispatch_uid="prometheus.update_multisig_transaction_metrics",
)
def update_multisig_transaction_metrics(
    sender: Type[Model],
    instance: MultisigTransaction,
    created: bool,
    **kwargs,
) -> None:
    if not created:
        return

    get_metrics().multisig_transaction_gauge.labels(origin=instance.origin).inc()
