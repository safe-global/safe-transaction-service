from typing import Type

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ContractAbi
from .tx_decoder import get_db_tx_decoder


@receiver(post_save, sender=ContractAbi, dispatch_uid='contract_abi.add_abi_to_tx_decoder')
def add_abi_to_tx_decoder(sender: Type[Model],
                          instance: ContractAbi,
                          created: bool, **kwargs) -> None:
    """
    When a `ContractAbi` is saved, TxDecoder must be updated
    :param sender: ContractAbi
    :param instance: Instance of ContractAbi
    :param created: `True` if model has just been created, `False` otherwise
    :param kwargs:
    :return:
    """

    if instance.abi:
        db_tx_decoder = get_db_tx_decoder()
        db_tx_decoder.add_abi(instance.abi)
