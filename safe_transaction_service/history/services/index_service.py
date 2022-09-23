import logging
from dataclasses import dataclass
from typing import Collection, List, Optional, OrderedDict, Union

from django.db import IntegrityError, transaction
from django.db.models import Min, Q

from eth_typing import ChecksumAddress
from hexbytes import HexBytes

from gnosis.eth import EthereumClient, EthereumClientProvider

from ..models import (
    EthereumBlock,
    EthereumTx,
    InternalTxDecoded,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeMasterCopy,
    SafeStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class IndexingStatus:
    current_block_number: int
    erc20_block_number: int
    erc20_synced: bool
    master_copies_block_number: int
    master_copies_synced: bool
    synced: bool


@dataclass
class ERC20IndexingStatus:
    current_block_number: int
    erc20_block_number: int
    erc20_synced: bool


class IndexingException(Exception):
    pass


class TransactionNotFoundException(IndexingException):
    pass


class TransactionWithoutBlockException(IndexingException):
    pass


class BlockNotFoundException(IndexingException):
    pass


class IndexServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            from django.conf import settings

            cls.instance = IndexService(
                EthereumClientProvider(),
                settings.ETH_REORG_BLOCKS,
                settings.ETH_L2_NETWORK,
                settings.ALERT_OUT_OF_SYNC_EVENTS_THRESHOLD,
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


# TODO Test IndexService
class IndexService:
    def __init__(
        self,
        ethereum_client: EthereumClient,
        eth_reorg_blocks: int,
        eth_l2_network: bool,
        alert_out_of_sync_events_threshold: float,
    ):
        self.ethereum_client = ethereum_client
        self.eth_reorg_blocks = eth_reorg_blocks
        self.eth_l2_network = eth_l2_network
        self.alert_out_of_sync_events_threshold = alert_out_of_sync_events_threshold

    def block_get_or_create_from_block_hash(self, block_hash: int):
        try:
            return EthereumBlock.objects.get(block_hash=block_hash)
        except EthereumBlock.DoesNotExist:
            current_block_number = (
                self.ethereum_client.current_block_number
            )  # For reorgs
            block = self.ethereum_client.get_block(block_hash)
            confirmed = (
                current_block_number - block["number"]
            ) >= self.eth_reorg_blocks
            return EthereumBlock.objects.get_or_create_from_block(
                block, confirmed=confirmed
            )

    def get_indexing_status(self) -> IndexingStatus:
        current_block_number = self.ethereum_client.current_block_number
        erc20_block_number = SafeContract.objects.aggregate(
            min_erc20_block_number=Min("erc20_block_number")
        )["min_erc20_block_number"]
        if erc20_block_number is None:  # Still nothing indexed
            erc20_block_number = current_block_number

        master_copies_block_number = SafeMasterCopy.objects.relevant().aggregate(
            min_master_copies_block_number=Min("tx_block_number")
        )["min_master_copies_block_number"]
        if master_copies_block_number is None:  # Still nothing indexed
            master_copies_block_number = current_block_number

        erc20_synced = (
            current_block_number - erc20_block_number <= self.eth_reorg_blocks
        )
        master_copies_synced = (
            current_block_number - master_copies_block_number <= self.eth_reorg_blocks
        )

        return IndexingStatus(
            current_block_number=current_block_number,
            erc20_block_number=erc20_block_number,
            erc20_synced=erc20_synced,
            master_copies_block_number=master_copies_block_number,
            master_copies_synced=master_copies_synced,
            synced=erc20_synced and master_copies_synced,
        )

    def get_erc20_indexing_status(self) -> ERC20IndexingStatus:
        current_block_number = self.ethereum_client.current_block_number
        erc20_block_number = SafeContract.objects.aggregate(
            min_erc20_block_number=Min("erc20_block_number")
        )["min_erc20_block_number"]
        if erc20_block_number is None:  # Still nothing indexed
            erc20_block_number = current_block_number
        synced = (current_block_number - erc20_block_number) <= self.eth_reorg_blocks

        return ERC20IndexingStatus(
            current_block_number=current_block_number,
            erc20_block_number=erc20_block_number,
            erc20_synced=synced,
        )

    def is_service_synced(self) -> bool:
        """
        :return: `True` if master copies and ERC20/721 are synced, `False` otherwise
        """

        # Use number of reorg blocks to consider as not synced
        reference_block_number = (
            self.ethereum_client.current_block_number - self.eth_reorg_blocks
        )
        synced = True
        for safe_master_copy in SafeMasterCopy.objects.relevant().filter(
            tx_block_number__lt=reference_block_number
        ):
            logger.error("Master Copy %s is out of sync", safe_master_copy.address)
            synced = False

        out_of_sync_contracts = SafeContract.objects.filter(
            erc20_block_number__lt=reference_block_number
        ).count()
        if out_of_sync_contracts > 0:
            total_number_of_contracts = SafeContract.objects.all().count()
            proportion_out_of_sync = out_of_sync_contracts / total_number_of_contracts
            # Ignore less than 10% of contracts out of sync
            if proportion_out_of_sync >= self.alert_out_of_sync_events_threshold:
                logger.error(
                    "%d Safe Contracts have ERC20/721 out of sync",
                    out_of_sync_contracts,
                )
                synced = False

        return synced

    def tx_create_or_update_from_tx_hash(self, tx_hash: str) -> "EthereumTx":
        try:
            ethereum_tx = EthereumTx.objects.get(tx_hash=tx_hash)
            # For txs stored before being mined
            if ethereum_tx.block is None:
                tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
                ethereum_block = self.block_get_or_create_from_block_hash(
                    tx_receipt["blockHash"]
                )
                ethereum_tx.update_with_block_and_receipt(ethereum_block, tx_receipt)
            return ethereum_tx
        except EthereumTx.DoesNotExist:
            tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
            ethereum_block = self.block_get_or_create_from_block_hash(
                tx_receipt["blockHash"]
            )
            tx = self.ethereum_client.get_transaction(tx_hash)
            return EthereumTx.objects.create_from_tx_dict(
                tx, tx_receipt=tx_receipt, ethereum_block=ethereum_block
            )

    def txs_create_or_update_from_tx_hashes(
        self, tx_hashes: Collection[Union[str, bytes]]
    ) -> List["EthereumTx"]:
        # Search first in database
        ethereum_txs_dict = OrderedDict.fromkeys(
            [HexBytes(tx_hash).hex() for tx_hash in tx_hashes]
        )
        db_ethereum_txs = EthereumTx.objects.filter(tx_hash__in=tx_hashes).exclude(
            block=None
        )
        for db_ethereum_tx in db_ethereum_txs:
            ethereum_txs_dict[db_ethereum_tx.tx_hash] = db_ethereum_tx

        # Retrieve from the node the txs missing from database
        tx_hashes_not_in_db = [
            tx_hash
            for tx_hash, ethereum_tx in ethereum_txs_dict.items()
            if not ethereum_tx
        ]
        if not tx_hashes_not_in_db:
            return list(ethereum_txs_dict.values())

        # Get receipts for hashes not in db
        tx_receipts = []
        for tx_hash, tx_receipt in zip(
            tx_hashes_not_in_db,
            self.ethereum_client.get_transaction_receipts(tx_hashes_not_in_db),
        ):
            tx_receipt = tx_receipt or self.ethereum_client.get_transaction_receipt(
                tx_hash
            )  # Retry fetching if failed
            if not tx_receipt:
                raise TransactionNotFoundException(
                    f"Cannot find tx-receipt with tx-hash={HexBytes(tx_hash).hex()}"
                )

            if tx_receipt.get("blockHash") is None:
                raise TransactionWithoutBlockException(
                    f"Cannot find blockHash for tx-receipt with "
                    f"tx-hash={HexBytes(tx_hash).hex()}"
                )

            tx_receipts.append(tx_receipt)

        # Get transactions for hashes not in db
        fetched_txs = self.ethereum_client.get_transactions(tx_hashes_not_in_db)
        block_hashes = set()
        txs = []
        for tx_hash, tx in zip(tx_hashes_not_in_db, fetched_txs):
            tx = tx or self.ethereum_client.get_transaction(
                tx_hash
            )  # Retry fetching if failed
            if not tx:
                raise TransactionNotFoundException(
                    f"Cannot find tx with tx-hash={HexBytes(tx_hash).hex()}"
                )

            if tx.get("blockHash") is None:
                raise TransactionWithoutBlockException(
                    f"Cannot find blockHash for tx with "
                    f"tx-hash={HexBytes(tx_hash).hex()}"
                )

            block_hashes.add(tx["blockHash"].hex())
            txs.append(tx)

        blocks = self.ethereum_client.get_blocks(block_hashes)
        block_dict = {}
        for block_hash, block in zip(block_hashes, blocks):
            block = block or self.ethereum_client.get_block(
                block_hash
            )  # Retry fetching if failed
            if not block:
                raise BlockNotFoundException(
                    f"Block with hash={block_hash} was not found"
                )
            assert block_hash == block["hash"].hex()
            block_dict[block["hash"]] = block

        # Create new transactions or update them if they have no receipt
        current_block_number = self.ethereum_client.current_block_number
        for tx, tx_receipt in zip(txs, tx_receipts):
            block = block_dict[tx["blockHash"]]
            confirmed = (
                current_block_number - block["number"]
            ) >= self.eth_reorg_blocks
            ethereum_block: EthereumBlock = (
                EthereumBlock.objects.get_or_create_from_block(
                    block, confirmed=confirmed
                )
            )
            try:
                with transaction.atomic():
                    ethereum_tx = EthereumTx.objects.create_from_tx_dict(
                        tx, tx_receipt=tx_receipt, ethereum_block=ethereum_block
                    )
                ethereum_txs_dict[HexBytes(ethereum_tx.tx_hash).hex()] = ethereum_tx
            except IntegrityError:  # Tx exists
                ethereum_tx = EthereumTx.objects.get(tx_hash=tx["hash"])
                # For txs stored before being mined
                ethereum_tx.update_with_block_and_receipt(ethereum_block, tx_receipt)
                ethereum_txs_dict[ethereum_tx.tx_hash] = ethereum_tx
        return list(ethereum_txs_dict.values())

    @transaction.atomic
    def _reprocess(self, addresses: List[str]):
        """
        Trigger processing of traces again. If addresses is empty, everything is reprocessed

        :param addresses:
        :return:
        """
        queryset = MultisigConfirmation.objects.filter(signature=None)
        if not addresses:
            logger.info("Remove onchain confirmations")
            queryset.delete()

        logger.info("Remove transactions automatically indexed")
        queryset = MultisigTransaction.objects.exclude(ethereum_tx=None).filter(
            Q(origin=None) | Q(origin="")
        )
        if addresses:
            queryset = queryset.filter(safe__in=addresses)
        queryset.delete()

        logger.info("Remove module transactions")
        queryset = ModuleTransaction.objects.all()
        if addresses:
            queryset = queryset.filter(safe__in=addresses)
        queryset.delete()

        logger.info("Remove Safe statuses")

        queryset = SafeStatus.objects.all()
        if addresses:
            queryset = queryset.filter(address__in=addresses)
        queryset.delete()

        logger.info("Mark all internal txs decoded as not processed")
        queryset = InternalTxDecoded.objects.all()
        if addresses:
            queryset = queryset.filter(internal_tx___from__in=addresses)
        queryset.update(processed=False)

    def reprocess_addresses(self, addresses: List[str]):
        """
        Given a list of safe addresses it will delete all `SafeStatus`, conflicting `MultisigTxs` and will mark
        every `InternalTxDecoded` not processed to be processed again

        :param addresses: List of checksummed addresses or queryset
        :return: Number of `SafeStatus` deleted
        """
        if not addresses:
            return None

        return self._reprocess(addresses)

    def reprocess_all(self):
        return self._reprocess(None)

    def _reindex(
        self,
        indexer: "EthereumIndexer",  # noqa F821
        from_block_number: int,
        to_block_number: Optional[int] = None,
        block_process_limit: int = 100,
        addresses: Optional[ChecksumAddress] = None,
    ) -> int:
        """
        :param provider:
        :param from_block_number:
        :param to_block_number:
        :param block_process_limit:
        :param addresses:
        :return: Number of reindexed elements
        """
        assert (not to_block_number) or to_block_number > from_block_number

        ignore_addresses_on_log_filter = (
            indexer.IGNORE_ADDRESSES_ON_LOG_FILTER
            if hasattr(indexer, "IGNORE_ADDRESSES_ON_LOG_FILTER")
            else None
        )

        if addresses:
            indexer.IGNORE_ADDRESSES_ON_LOG_FILTER = (
                False  # Just process addresses provided
            )
        else:
            addresses = list(
                indexer.database_queryset.values_list("address", flat=True)
            )

        element_number: int = 0
        if not addresses:
            logger.warning("No addresses to process")
        else:
            logger.info("Start reindexing addresses %s", addresses)
            current_block_number = self.ethereum_client.current_block_number
            stop_block_number = (
                min(current_block_number, to_block_number)
                if to_block_number
                else current_block_number
            )
            for block_number in range(
                from_block_number, stop_block_number, block_process_limit
            ):
                elements = indexer.find_relevant_elements(
                    addresses,
                    block_number,
                    min(block_number + block_process_limit - 1, stop_block_number),
                )
                indexer.process_elements(elements)
                logger.info(
                    "Current block number %d, found %d traces/events",
                    block_number,
                    len(elements),
                )
                element_number += len(elements)

            logger.info("End reindexing addresses %s", addresses)

        # We changed attributes on the indexer, so better restore it
        indexer.IGNORE_ADDRESSES_ON_LOG_FILTER = ignore_addresses_on_log_filter
        return element_number

    def reindex_master_copies(
        self,
        from_block_number: int,
        to_block_number: Optional[int] = None,
        block_process_limit: int = 100,
        addresses: Optional[ChecksumAddress] = None,
    ) -> int:
        """
        Reindexes master copies in parallel with the current running indexer, so service will have no missing txs
        while reindexing

        :param from_block_number: Block number to start indexing from
        :param to_block_number: Block number to stop indexing on
        :param block_process_limit: Number of blocks to process each time
        :param addresses: Master Copy or Safes(for L2 event processing) addresses. If not provided,
            all master copies will be used
        """

        # TODO Refactor EthereumIndexer to fix circular imports
        from ..indexers import InternalTxIndexerProvider, SafeEventsIndexerProvider

        indexer = (
            SafeEventsIndexerProvider
            if self.eth_l2_network
            else InternalTxIndexerProvider
        )()

        return self._reindex(
            indexer,
            from_block_number,
            to_block_number=to_block_number,
            block_process_limit=block_process_limit,
            addresses=addresses,
        )

    def reindex_erc20_events(
        self,
        from_block_number: int,
        to_block_number: Optional[int] = None,
        block_process_limit: int = 100,
        addresses: Optional[ChecksumAddress] = None,
    ) -> int:
        """
        Reindexes erc20/721 events parallel with the current running indexer, so service will have no missing
        events while reindexing

        :param from_block_number: Block number to start indexing from
        :param to_block_number: Block number to stop indexing on
        :param block_process_limit: Number of blocks to process each time
        :param addresses: Safe addresses. If not provided, all Safe addresses will be used
        """
        assert (not to_block_number) or to_block_number > from_block_number

        from ..indexers import Erc20EventsIndexerProvider

        indexer = Erc20EventsIndexerProvider()
        return self._reindex(
            indexer,
            from_block_number,
            to_block_number=to_block_number,
            block_process_limit=block_process_limit,
            addresses=addresses,
        )
