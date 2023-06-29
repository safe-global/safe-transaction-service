import logging
from typing import Callable, List, Optional

from django.db import transaction

from hexbytes import HexBytes

from gnosis.eth import EthereumClient, EthereumClientProvider

from ..indexers import (
    Erc20EventsIndexerProvider,
    InternalTxIndexerProvider,
    ProxyFactoryIndexerProvider,
    SafeEventsIndexerProvider,
)
from ..models import EthereumBlock, IndexingStatus, ProxyFactory, SafeMasterCopy

logger = logging.getLogger(__name__)


class ReorgServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            from django.conf import settings

            cls.instance = ReorgService(
                EthereumClientProvider(), settings.ETH_REORG_BLOCKS
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


# TODO Test ReorgService
class ReorgService:
    def __init__(
        self,
        ethereum_client: EthereumClient,
        eth_reorg_blocks: int,
        eth_reorg_rewind_blocks: Optional[int] = 10,
    ):
        """
        :param ethereum_client:
        :param eth_reorg_blocks: Minimum number of blocks to consider a block confirmed and safe to rely on. In Mainnet
            10 blocks is considered safe
        :param eth_reorg_rewind_blocks: Number of blocks to rewind indexing when a reorg is found
        """
        self.ethereum_client = ethereum_client
        self.eth_reorg_blocks = eth_reorg_blocks
        self.eth_reorg_rewind_blocks = eth_reorg_rewind_blocks

        # List with functions for database models to recover from reorgs
        self.reorg_functions: List[Callable[[int], int]] = [
            lambda block_number: ProxyFactory.objects.filter(
                tx_block_number__gt=block_number
            ).update(tx_block_number=block_number),
            lambda block_number: SafeMasterCopy.objects.filter(
                tx_block_number__gt=block_number
            ).update(tx_block_number=block_number),
            lambda block_number: int(
                IndexingStatus.objects.set_erc20_721_indexing_status(block_number)
            ),
        ]

        # Indexers to reset
        self.indexer_providers = [
            Erc20EventsIndexerProvider,
            InternalTxIndexerProvider,
            ProxyFactoryIndexerProvider,
            SafeEventsIndexerProvider,
        ]

    def check_reorgs(self) -> Optional[int]:
        """
        :return: Number of the oldest block with reorg detected. `None` if not reorg found
        """
        current_block_number = self.ethereum_client.current_block_number
        to_block = current_block_number - self.eth_reorg_blocks
        for database_block in (
            EthereumBlock.objects.not_confirmed(to_block_number=to_block)
            .only("number", "block_hash", "confirmed")
            .order_by("number")
            .iterator()
        ):
            blockchain_block, blockchain_next_block = self.ethereum_client.get_blocks(
                [database_block.number, database_block.number + 1],
                full_transactions=False,
            )
            if (
                HexBytes(blockchain_block["hash"])
                == HexBytes(blockchain_next_block["parentHash"])
                == HexBytes(database_block.block_hash)
            ):
                logger.debug(
                    "Block with number=%d and hash=%s is matching blockchain one, setting as confirmed",
                    database_block.number,
                    HexBytes(blockchain_block["hash"]).hex(),
                )
                database_block.set_confirmed()
            else:
                logger.warning(
                    "Block with number=%d and hash=%s is not matching blockchain hash=%s, reorg found",
                    database_block.number,
                    HexBytes(database_block.block_hash).hex(),
                    HexBytes(blockchain_block["hash"]).hex(),
                )
                return database_block.number

    @transaction.atomic
    def reset_all_to_block(self, block_number: int) -> int:
        """
        Reset database fields to a block to start reindexing from that block.

        :param block_number:
        :return: Number of updated models
        """
        updated = 0
        for reorg_function in self.reorg_functions:
            updated += reorg_function(block_number)

        # Reset indexer status and caches
        for indexer_provider in self.indexer_providers:
            indexer_provider.del_singleton()

        return updated

    @transaction.atomic
    def recover_from_reorg(self, reorg_block_number: int) -> int:
        """
        Reset database fields to a block to start reindexing from that block
        and remove blocks greater or equal than `reorg_block_number`.

        :param reorg_block_number:
        :return: Return number of elements updated
        """
        safe_reorg_block_number = max(
            reorg_block_number - self.eth_reorg_rewind_blocks, 0
        )

        updated = self.reset_all_to_block(safe_reorg_block_number)
        number_deleted_blocks, _ = EthereumBlock.objects.filter(
            number__gte=reorg_block_number
        ).delete()
        logger.warning(
            "Reorg of block-number=%d fixed, indexing was reset to safe block=%d, %d elements updated and %d blocks deleted",
            reorg_block_number,
            safe_reorg_block_number,
            updated,
            number_deleted_blocks,
        )
        return updated
