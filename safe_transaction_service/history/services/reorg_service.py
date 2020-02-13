import logging
from typing import Dict, Optional

from django.db import models, transaction

from hexbytes import HexBytes

from gnosis.eth import EthereumClient, EthereumClientProvider

from ..models import EthereumBlock, ProxyFactory, SafeContract, SafeMasterCopy

logger = logging.getLogger(__name__)


class ReorgServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = ReorgService(EthereumClientProvider())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


# TODO Test ReorgService
class ReorgService:
    SAFE_CONFIRMATIONS = 7

    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        # Dictionary with Django model and attribute for reorgs
        self.reorg_models: Dict[models.Model, str] = {
            SafeMasterCopy: 'tx_block_number',
            ProxyFactory: 'tx_block_number',
            SafeContract: 'erc20_block_number',
        }

    def check_reorgs(self) -> Optional[int]:
        """
        :return: Number of oldest block with reorg detected. `None` if not reorg found
        """
        current_block_number = self.ethereum_client.current_block_number
        to_block = current_block_number - self.SAFE_CONFIRMATIONS
        for database_block in EthereumBlock.objects.not_confirmed(to_block_number=to_block):
            blockchain_block = self.ethereum_client.get_block(database_block.number, full_transactions=False)
            if HexBytes(blockchain_block['hash']) == HexBytes(database_block.block_hash):
                database_block.set_confirmed()
            else:
                logger.warning('Reorg found for block-number=%d', database_block.number)
                return database_block.number

    def reset_all_to_block(self, block_number: int) -> int:
        """
        Reset database fields to a block to start reindexing from that block. It's useful when you want to trigger
        a indexation for txs that are not appearing on database but you don't want to delete anything
        :param block_number:
        :return: Number of updated models
        """
        updated = 0
        for model, field in self.reorg_models.items():
            updated += model.objects.filter(
                **{field + '__gt': block_number}
            ).update(
                **{field: block_number}
            )
        return updated

    @transaction.atomic
    def recover_from_reorg(self, first_reorg_block_number: int) -> int:
        """
        :param first_reorg_block_number:
        :return: Return number of elements updated
        """
        safe_reorg_block_number = min(first_reorg_block_number - 250, 0)  # Reindex last hour

        updated = 0
        for model, field in self.reorg_models.items():
            updated += model.objects.filter(
                **{field + '__gte': first_reorg_block_number}
            ).update(
                **{field: safe_reorg_block_number}
            )

        EthereumBlock.objects.filter(number__gte=first_reorg_block_number).delete()
        logger.warning('Reorg of block-number=%d fixed, %d elements updated', first_reorg_block_number, updated)
        return updated
