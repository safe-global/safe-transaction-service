# SPDX-License-Identifier: FSL-1.1-MIT
from logging import getLogger

from django.db.models import Model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import PolicyContract

logger = getLogger(__name__)


@receiver(
    post_save,
    sender=PolicyContract,
    dispatch_uid="policy_contract.clear_name_cache_on_save",
)
@receiver(
    post_delete,
    sender=PolicyContract,
    dispatch_uid="policy_contract.clear_name_cache_on_delete",
)
def policy_contract_clear_cache(
    sender: type[Model], instance: PolicyContract, **kwargs
) -> None:
    """
    Clear the address to policy name cache, so a policy registered or removed through the
    admin is picked up without a restart
    """
    PolicyContract.objects.get_name_for_address.cache_clear()
