import logging
from typing import Type

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ContractAbi
from .tx_decoder import get_db_tx_decoder

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ContractAbi, dispatch_uid='contract_abi.load_abi_in_tx_decoder')
def load_abi_in_tx_decoder(sender: Type[Model],
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
        if db_tx_decoder.load_abi(instance.abi):
            logger.info('ABI for ContractAbi %s was loaded on the TxDecoder', instance)
