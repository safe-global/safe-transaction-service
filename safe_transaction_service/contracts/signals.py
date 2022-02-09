import logging
from typing import Sequence, Type

from django.core.cache import cache as django_cache
from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from eth_typing import ChecksumAddress

from .models import Contract, ContractAbi
from .tx_decoder import get_db_tx_decoder, is_db_tx_decoder_loaded

logger = logging.getLogger(__name__)


def get_contract_cache_key(address: ChecksumAddress) -> str:
    return f"contracts:{address}"


def clear_contracts_cache(addresses: Sequence[ChecksumAddress]) -> None:
    keys = [get_contract_cache_key(address) for address in addresses]
    return django_cache.delete_many(keys)


@receiver(post_save, sender=Contract, dispatch_uid="contract.clear_cache")
def clear_contract_cache(
    sender: Type[Model], instance: Contract, created: bool, **kwargs
) -> None:
    """
    Clear Contract cache when a contract is updated

    :param sender:
    :param instance:
    :param created:
    :param kwargs:
    :return:
    """
    return clear_contracts_cache([instance.address])


@receiver(
    post_save, sender=ContractAbi, dispatch_uid="contract_abi.add_abi_to_tx_decoder"
)
def add_abi_in_tx_decoder(
    sender: Type[Model], instance: ContractAbi, created: bool, **kwargs
) -> None:
    """
    When a `ContractAbi` is saved, TxDecoder must be updated and caches must be flushed

    :param sender: ContractAbi
    :param instance: Instance of ContractAbi
    :param created: `True` if model has just been created, `False` otherwise
    :param kwargs:
    :return:
    """

    clear_contracts_cache(instance.contracts.values_list("address", flat=True))
    if instance.abi:
        if is_db_tx_decoder_loaded():
            db_tx_decoder = get_db_tx_decoder()
            if db_tx_decoder.add_abi(instance.abi):
                logger.info(
                    "ABI for ContractAbi %s was loaded on the TxDecoder", instance
                )
