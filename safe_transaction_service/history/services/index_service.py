import logging
from dataclasses import dataclass
from typing import Collection, Optional, OrderedDict, Union

from django.db import transaction
from django.db.models import Min, Q

from eth_typing import ChecksumAddress, Hash32
from hexbytes import HexBytes
from safe_eth.eth import EthereumClient, get_auto_ethereum_client
from safe_eth.util.util import to_0x_hex_str

from ..models import (
    EthereumBlock,
    EthereumTx,
)
from ..models import IndexingStatus as IndexingStatusDb
from ..models import (
    InternalTx,
    InternalTxDecoded,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeLastStatus,
    SafeMasterCopy,
    SafeStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class AllIndexingStatus:
    current_block_number: int
    current_block_timestamp: int
    erc20_block_number: int
    erc20_block_timestamp: int
    erc20_synced: bool
    master_copies_block_number: int
    master_copies_block_timestamp: int
    master_copies_synced: bool
    synced: bool


@dataclass
class SpecificIndexingStatus:
    current_block_number: int
    block_number: int
    synced: bool


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
                get_auto_ethereum_client(),
                settings.ETH_REORG_BLOCKS,
                settings.ETH_L2_NETWORK,
                settings.ETH_INTERNAL_TX_DECODED_PROCESS_BATCH,
                settings.PROCESSING_ENABLE_OUT_OF_ORDER_CHECK,
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class IndexService:
    def __init__(
        self,
        ethereum_client: EthereumClient,
        eth_reorg_blocks: int,
        eth_l2_network: bool,
        eth_internal_tx_decoded_process_batch: int,
        processing_enable_out_of_order_check: bool,
    ):
        self.ethereum_client = ethereum_client
        self.eth_reorg_blocks = eth_reorg_blocks
        self.eth_l2_network = eth_l2_network
        self.eth_internal_tx_decoded_process_batch = (
            eth_internal_tx_decoded_process_batch
        )
        self.processing_enable_out_of_order_check = processing_enable_out_of_order_check

        # Prevent circular import
        from ..indexers.tx_processor import SafeTxProcessor, SafeTxProcessorProvider

        self.tx_processor: SafeTxProcessor = SafeTxProcessorProvider()

    def get_erc20_721_current_indexing_block_number(self) -> int:
        return IndexingStatusDb.objects.get_erc20_721_indexing_status().block_number

    def get_master_copies_current_indexing_block_number(self) -> Optional[int]:
        return SafeMasterCopy.objects.relevant().aggregate(
            min_master_copies_block_number=Min("tx_block_number")
        )["min_master_copies_block_number"]

    def get_erc20_indexing_status(
        self, current_block_number: int
    ) -> SpecificIndexingStatus:
        erc20_block_number = min(
            max(self.get_erc20_721_current_indexing_block_number() - 1, 0),
            current_block_number,
        )
        erc20_synced = (
            current_block_number - erc20_block_number <= self.eth_reorg_blocks
        )
        return SpecificIndexingStatus(
            current_block_number, erc20_block_number, erc20_synced
        )

    def get_master_copies_indexing_status(
        self, current_block_number: int
    ) -> SpecificIndexingStatus:
        if (
            master_copies_current_indexing_block_number := self.get_master_copies_current_indexing_block_number()
        ) is None:
            master_copies_block_number = current_block_number
        else:
            master_copies_block_number = min(
                max(master_copies_current_indexing_block_number - 1, 0),
                current_block_number,
            )

        master_copies_synced = (
            current_block_number - master_copies_block_number <= self.eth_reorg_blocks
        )
        return SpecificIndexingStatus(
            current_block_number, master_copies_block_number, master_copies_synced
        )

    def get_indexing_status(self) -> AllIndexingStatus:
        current_block = self.ethereum_client.get_block("latest")
        current_block_number = current_block["number"]

        erc20_indexing_status = self.get_erc20_indexing_status(current_block_number)
        master_copies_indexing_status = self.get_master_copies_indexing_status(
            current_block_number
        )

        if (
            erc20_indexing_status.block_number
            == master_copies_indexing_status.block_number
            == current_block_number
        ):
            erc20_block, master_copies_block = [current_block, current_block]
        else:
            erc20_block, master_copies_block = self.ethereum_client.get_blocks(
                [
                    erc20_indexing_status.block_number,
                    master_copies_indexing_status.block_number,
                ]
            )
        current_block_timestamp = current_block["timestamp"]
        erc20_block_timestamp = erc20_block["timestamp"]
        master_copies_block_timestamp = master_copies_block["timestamp"]

        return AllIndexingStatus(
            current_block_number=current_block_number,
            current_block_timestamp=current_block_timestamp,
            erc20_block_number=erc20_indexing_status.block_number,
            erc20_block_timestamp=erc20_block_timestamp,
            erc20_synced=erc20_indexing_status.synced,
            master_copies_block_number=master_copies_indexing_status.block_number,
            master_copies_block_timestamp=master_copies_block_timestamp,
            master_copies_synced=master_copies_indexing_status.synced,
            synced=erc20_indexing_status.synced
            and master_copies_indexing_status.synced,
        )

    def is_service_synced(self) -> bool:
        """
        :return: `True` if master copies and ERC20/721 are synced, `False` otherwise
        """

        try:
            current_block_number = self.ethereum_client.current_block_number
        except (IOError, ValueError):
            # If there's an error connecting to the node or invalid response we consider the service as out of sync
            return False

        # Use number of reorg blocks to consider as not synced
        reference_block_number = current_block_number - self.eth_reorg_blocks
        synced: bool = True
        for safe_master_copy in SafeMasterCopy.objects.relevant().filter(
            tx_block_number__lt=reference_block_number
        ):
            logger.error("Master Copy %s is out of sync", safe_master_copy.address)
            synced = False

        if self.get_erc20_721_current_indexing_block_number() < reference_block_number:
            logger.error("Safe Contracts have ERC20/721 out of sync")
            synced = False

        return synced

    def txs_create_or_update_from_block_hashes(
        self, block_hashes: set[Hash32]
    ) -> tuple[int, dict[Hash32, EthereumBlock]]:
        block_hashes = list(block_hashes)  # Iterate in a defined order
        blocks = self.ethereum_client.get_blocks(block_hashes)

        # Validate blocks from RPC
        for block_hash, block in zip(block_hashes, blocks):
            if not block:
                raise BlockNotFoundException(
                    f"Block with hash={block_hash} was not found"
                )
            assert block_hash == to_0x_hex_str(
                block["hash"]
            ), f"{block_hash} does not match retrieved block hash"

        current_block_number = self.ethereum_client.current_block_number
        ethereum_blocks_to_insert = [
            EthereumBlock.objects.from_block_dict(
                block,
                confirmed=(current_block_number - block["number"])
                >= self.eth_reorg_blocks,
            )
            for block in blocks
        ]
        inserted = EthereumBlock.objects.bulk_create_from_generator(
            iter(ethereum_blocks_to_insert), ignore_conflicts=True
        )
        return inserted, {
            HexBytes(ethereum_block.block_hash): ethereum_block
            for ethereum_block in ethereum_blocks_to_insert
        }

    def txs_create_or_update_from_tx_hashes(
        self, tx_hashes: Collection[Union[str, bytes]]
    ) -> list["EthereumTx"]:
        """
        :param tx_hashes:
        :return: List of EthereumTx in the same order that `tx_hashes` were provided
        """
        logger.debug("Don't retrieve existing txs on DB. Find them first")
        # Search first in database
        ethereum_txs_dict = OrderedDict.fromkeys(
            [HexBytes(tx_hash) for tx_hash in tx_hashes]
        )
        db_ethereum_txs = EthereumTx.objects.filter(tx_hash__in=tx_hashes).exclude(
            block=None
        )
        for db_ethereum_tx in db_ethereum_txs:
            ethereum_txs_dict[HexBytes(db_ethereum_tx.tx_hash)] = db_ethereum_tx
        logger.debug("Found %d existing txs on DB", len(db_ethereum_txs))

        # Retrieve from the node the txs missing from database
        tx_hashes_not_in_db = [
            tx_hash
            for tx_hash, ethereum_tx in ethereum_txs_dict.items()
            if not ethereum_tx
        ]
        logger.debug("Retrieve from RPC %d missing txs on DB", len(tx_hashes_not_in_db))
        if not tx_hashes_not_in_db:
            return list(ethereum_txs_dict.values())

        # Get receipts for hashes not in db. First get the receipts as they guarantee tx is mined and confirmed
        logger.debug("Get tx receipts for hashes not on db")
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
                    f"Cannot find tx-receipt with tx-hash={to_0x_hex_str(HexBytes(tx_hash))}"
                )

            if tx_receipt.get("blockHash") is None:
                raise TransactionWithoutBlockException(
                    f"Cannot find blockHash for tx-receipt with "
                    f"tx-hash={to_0x_hex_str(HexBytes(tx_hash))}"
                )

            tx_receipts.append(tx_receipt)

        logger.debug("Got tx receipts. Now getting transactions not on db")
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
                    f"Cannot find tx with tx-hash={to_0x_hex_str(HexBytes(tx_hash))}"
                )

            if tx.get("blockHash") is None:
                raise TransactionWithoutBlockException(
                    f"Cannot find blockHash for tx with "
                    f"tx-hash={to_0x_hex_str(HexBytes(tx_hash))}"
                )

            block_hashes.add(to_0x_hex_str(tx["blockHash"]))
            txs.append(tx)

        logger.debug(
            "Got txs from RPC. Getting and inserting %d blocks", len(block_hashes)
        )
        number_inserted_blocks, blocks = self.txs_create_or_update_from_block_hashes(
            block_hashes
        )
        logger.debug("Inserted %d blocks", number_inserted_blocks)

        logger.debug("Inserting %d transactions", len(txs))
        # Create new transactions or ignore if they already exist
        ethereum_txs_to_insert = [
            EthereumTx.objects.from_tx_dict(tx, tx_receipt)
            for tx, tx_receipt in zip(txs, tx_receipts)
        ]
        number_inserted_txs = EthereumTx.objects.bulk_create_from_generator(
            iter(ethereum_txs_to_insert), ignore_conflicts=True
        )
        for ethereum_tx, tx in zip(ethereum_txs_to_insert, txs):
            # Trust they were inserted and add them to the txs dictionary
            assert ethereum_tx.tx_hash == to_0x_hex_str(
                tx["hash"]
            ), f"{ethereum_tx.tx_hash} does not match retrieved tx hash"
            ethereum_tx.block = blocks[tx["blockHash"]]
            ethereum_txs_dict[HexBytes(ethereum_tx.tx_hash)] = ethereum_tx
            # Block info is required for traces

        logger.debug("Inserted %d transactions", number_inserted_txs)

        logger.debug("Blocks, transactions and receipts were inserted")

        return list(ethereum_txs_dict.values())

    @transaction.atomic
    def _reprocess(self, addresses: list[str]):
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
            Q(origin__exact={})
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

        logger.info("Remove Safe Last statuses")
        queryset = SafeLastStatus.objects.all()
        if addresses:
            queryset = queryset.filter(address__in=addresses)
        queryset.delete()

        logger.info("Mark all internal txs decoded as not processed")
        queryset = InternalTxDecoded.objects.all()
        if addresses:
            queryset = queryset.filter(internal_tx___from__in=addresses)
        queryset.update(processed=False)

    @transaction.atomic
    def fix_out_of_order(
        self, address: ChecksumAddress, internal_tx: InternalTx
    ) -> None:
        """
        Fix a Safe that has transactions out of order (not processed transactions
        in between processed ones, usually due a reindex), by marking
        them as not processed from the `internal_tx` where the issue was detected.

        :param address: Safe to fix
        :param internal_tx: Only reprocess transactions from `internal_tx` and newer
        :return:
        """

        timestamp = internal_tx.timestamp
        tx_hash_hex = to_0x_hex_str(HexBytes(internal_tx.ethereum_tx_id))
        logger.info(
            "[%s] Fixing out of order from tx %s with timestamp %s",
            address,
            tx_hash_hex,
            timestamp,
        )
        logger.info(
            "[%s] Marking InternalTxDecoded newer than timestamp as not processed",
            address,
        )
        InternalTxDecoded.objects.filter(
            internal_tx___from=address, internal_tx__timestamp__gte=timestamp
        ).update(processed=False)
        logger.info("[%s] Removing SafeStatus newer than timestamp", address)
        SafeStatus.objects.filter(
            address=address, internal_tx__timestamp__gte=timestamp
        ).delete()
        logger.info("[%s] Removing SafeLastStatus", address)
        SafeLastStatus.objects.filter(address=address).delete()
        logger.info("[%s] Ended fixing out of order", address)

    def process_all_decoded_txs(self) -> int:
        """
        Process all the pending `InternalTxDecoded` for every Safe

        :return: Number of `InternalTxDecoded` processed
        """
        # Use chunks for memory issues
        total_processed_txs = 0

        # Don't check out of order multiple times for a Safe
        checked_out_of_order: set[ChecksumAddress] = set()

        while True:
            logger.debug("Getting pending transactions to process for all Safes")
            internal_txs_decoded = list(
                InternalTxDecoded.objects.pending_for_safes()[
                    : self.eth_internal_tx_decoded_process_batch
                ]
            )
            logger.debug(
                "Got %d pending transactions to process for all Safes",
                len(internal_txs_decoded),
            )
            if not internal_txs_decoded:
                break

            # Check if a new decoded tx appeared before other already processed (due to a reindex)
            if self.processing_enable_out_of_order_check:
                safe_addresses_to_check = {
                    internal_tx_decoded.internal_tx._from
                    for internal_tx_decoded in internal_txs_decoded
                    if internal_tx_decoded.internal_tx._from not in checked_out_of_order
                }
                logger.info(
                    "Checking out of order transactions for %d Safes",
                    len(safe_addresses_to_check),
                )
                for safe_address in safe_addresses_to_check:
                    if InternalTxDecoded.objects.out_of_order_for_safe(safe_address):
                        logger.error(
                            "[%s] Found out of order transactions", safe_address
                        )
                        self.fix_out_of_order(
                            safe_address,
                            InternalTxDecoded.objects.pending_for_safe(safe_address)[
                                0
                            ].internal_tx,
                        )
                    checked_out_of_order.add(safe_address)
                logger.info(
                    "Checked out of order transactions for %d Safes",
                    len(safe_addresses_to_check),
                )

            logger.info(
                "Processing batch of %d decoded transactions",
                len(internal_txs_decoded),
            )
            total_processed_txs += len(
                self.tx_processor.process_decoded_transactions(internal_txs_decoded)
            )
        return total_processed_txs

    def process_decoded_txs_for_safe(self, safe_address: ChecksumAddress) -> int:
        """
        Process all the pending `InternalTxDecoded` for a Safe

        :param safe_address:
        :return: Number of `InternalTxDecoded` processed
        """

        # Check if a new decoded tx appeared before other already processed (due to a reindex)
        if self.processing_enable_out_of_order_check:
            if InternalTxDecoded.objects.out_of_order_for_safe(safe_address):
                logger.error("[%s] Found out of order transactions", safe_address)
                self.fix_out_of_order(
                    safe_address,
                    InternalTxDecoded.objects.pending_for_safe(safe_address)[
                        0
                    ].internal_tx,
                )

        # Use chunks for memory issues
        total_processed_txs = 0
        while True:
            internal_txs_decoded = list(
                InternalTxDecoded.objects.pending_for_safe(safe_address)[
                    : self.eth_internal_tx_decoded_process_batch
                ]
            )
            if not internal_txs_decoded:
                break
            total_processed_txs += len(
                self.tx_processor.process_decoded_transactions(internal_txs_decoded)
            )
        return total_processed_txs

    def reprocess_addresses(self, addresses: list[ChecksumAddress]):
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
        return self._reprocess([])

    def _reindex(
        self,
        indexer: "EthereumIndexer",  # noqa F821
        from_block_number: int,
        to_block_number: Optional[int] = None,
        block_process_limit: int = 100,
        addresses: Optional[ChecksumAddress] = None,
    ) -> int:
        """
        :param indexer: A new instance must be provider, providing the singleton one can break indexing
        :param from_block_number:
        :param to_block_number:
        :param block_process_limit:
        :param addresses:
        :return: Number of reindexed elements
        """
        assert (not to_block_number) or to_block_number > from_block_number

        if addresses:
            # Just process addresses provided
            # No issues on modifying the indexer as we should be provided with a new instance
            indexer.IGNORE_ADDRESSES_ON_LOG_FILTER = False
        else:
            addresses = set(indexer.database_queryset.values_list("address", flat=True))

        element_number: int = 0
        if not addresses:
            logger.warning("No addresses to process")
        else:
            # Don't log all the addresses
            addresses_len = len(addresses)
            addresses_str = (
                str(addresses)
                if addresses_len < 10
                else f"{addresses_len} addresses..."
            )
            logger.info("Start reindexing addresses %s", addresses_str)
            current_block_number = self.ethereum_client.current_block_number
            stop_block_number = (
                min(current_block_number, to_block_number)
                if to_block_number
                else current_block_number
            )
            for block_number in range(
                from_block_number, stop_block_number + 1, block_process_limit
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

            logger.info("End reindexing addresses %s", addresses_str)

        return element_number

    def reindex_master_copies(
        self,
        from_block_number: int,
        to_block_number: Optional[int] = None,
        block_process_limit: int = 100,
        addresses: Optional[ChecksumAddress] = None,
    ) -> int:
        """
        Reindex master copies in parallel with the current running indexer, so service will have no missing txs
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
            SafeEventsIndexerProvider.get_new_instance()
            if self.eth_l2_network
            else InternalTxIndexerProvider.get_new_instance()
        )

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
        Reindex erc20/721 events parallel with the current running indexer, so service will have no missing
        events while reindexing

        :param from_block_number: Block number to start indexing from
        :param to_block_number: Block number to stop indexing on
        :param block_process_limit: Number of blocks to process each time
        :param addresses: Safe addresses. If not provided, all Safe addresses will be used
        """
        assert (not to_block_number) or to_block_number > from_block_number

        from ..indexers import Erc20EventsIndexerProvider

        indexer = Erc20EventsIndexerProvider.get_new_instance()
        return self._reindex(
            indexer,
            from_block_number,
            to_block_number=to_block_number,
            block_process_limit=block_process_limit,
            addresses=addresses,
        )
