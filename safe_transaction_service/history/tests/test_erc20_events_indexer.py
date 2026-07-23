# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import TestCase

from hexbytes import HexBytes
from safe_eth.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..indexers import Erc20EventsIndexerProvider
from ..indexers.erc20_events_indexer import AddressesCache
from ..models import (
    ERC20Transfer,
    EthereumBlock,
    EthereumTx,
    IndexingStatus,
    SafeRelevantTransaction,
)
from .factories import EthereumTxFactory, SafeContractFactory
from .mocks.mocks_erc20_events_indexer import log_receipt_mock


class TestErc20EventsIndexer(EthereumTestCaseMixin, TestCase):
    def setUp(self) -> None:
        Erc20EventsIndexerProvider.del_singleton()
        self.erc20_events_indexer = Erc20EventsIndexerProvider()
        EthereumBlock.objects.get_timestamp_by_hash.cache_clear()

    def tearDown(self) -> None:
        Erc20EventsIndexerProvider.del_singleton()

    @classmethod
    def tearDownClass(cls) -> None:
        EthereumBlock.objects.get_timestamp_by_hash.cache_clear()
        return super().tearDownClass()

    def test_erc20_events_indexer(self):
        erc20_events_indexer = self.erc20_events_indexer
        erc20_events_indexer.confirmations = 0
        self.assertEqual(erc20_events_indexer.start(), (0, 0))

        account = self.ethereum_test_account
        amount = 10
        erc20_contract = self.deploy_example_erc20(amount, account.address)

        safe_contract = SafeContractFactory()
        IndexingStatus.objects.set_erc20_721_indexing_status(0)
        tx_hash = self.ethereum_client.erc20.send_tokens(
            safe_contract.address, amount, erc20_contract.address, account.key
        )

        self.assertFalse(EthereumTx.objects.filter(tx_hash=tx_hash).exists())
        self.assertFalse(
            ERC20Transfer.objects.tokens_used_by_address(safe_contract.address)
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 0)
        self.assertEqual(
            erc20_events_indexer.start(),
            (1, self.ethereum_client.current_block_number + 1),
        )

        # Store one entry for the sender and other for the receiver
        self.assertEqual(SafeRelevantTransaction.objects.count(), 2)
        self.assertEqual(
            SafeRelevantTransaction.objects.filter(
                safe=safe_contract.address, ethereum_tx_id=tx_hash
            ).count(),
            1,
        )

        # Erc20/721 last indexed block number is stored on IndexingStatus
        self.assertGreater(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 0
        )

        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number,
            self.ethereum_client.current_block_number
            - erc20_events_indexer.confirmations
            + 1,
        )
        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx_hash).exists())
        self.assertTrue(
            ERC20Transfer.objects.tokens_used_by_address(safe_contract.address)
        )

        self.assertEqual(
            ERC20Transfer.objects.to_or_from(safe_contract.address).count(), 1
        )

        block_number = self.ethereum_client.get_transaction(tx_hash)["blockNumber"]
        event = self.ethereum_client.erc20.get_total_transfer_history(
            from_block=block_number, to_block=block_number
        )[0]
        self.assertIn("value", event["args"])

    def test_element_already_processed_checker(self):
        # Create transaction in db so not fetching of transaction is needed
        for log_receipt in log_receipt_mock:
            tx_hash = log_receipt["transactionHash"]
            block_hash = log_receipt["blockHash"]
            EthereumTxFactory(tx_hash=tx_hash, block__block_hash=block_hash)

        # After the first processing transactions will be cached to prevent reprocessing
        processed_element_cache = self.erc20_events_indexer.element_already_processed_checker._processed_element_cache
        self.assertEqual(len(processed_element_cache), 0)
        self.assertEqual(
            len(self.erc20_events_indexer.process_elements(log_receipt_mock)), 1
        )
        self.assertEqual(len(processed_element_cache), 1)

        # Transactions are cached and will not be reprocessed
        self.assertEqual(
            len(self.erc20_events_indexer.process_elements(log_receipt_mock)), 0
        )
        self.assertEqual(
            len(self.erc20_events_indexer.process_elements(log_receipt_mock)), 0
        )

        # Cleaning the cache will reprocess the transactions again
        self.erc20_events_indexer.element_already_processed_checker.clear()
        self.assertEqual(
            len(self.erc20_events_indexer.process_elements(log_receipt_mock)), 1
        )

    def test_process_elements_reorged_block_is_flagged_not_confirmed(self):
        """
        A reorg can move an already-indexed tx to a new block. The event then
        references a block hash missing from database while the tx is still
        stored under the stale block. Processing must fail so the range is
        retried without marking the events as processed, but the stale block
        must be left as not confirmed even though the storing transaction
        rolls back, otherwise `check_reorgs_task` will never detect the reorg
        and the indexer will retry the same range forever.
        """
        log_receipt = log_receipt_mock[0]
        ethereum_tx = EthereumTxFactory(
            tx_hash=log_receipt["transactionHash"],
            block__confirmed=True,  # Deep enough block, not checked for reorgs
        )
        stale_block = ethereum_tx.block
        self.assertNotEqual(
            HexBytes(stale_block.block_hash), HexBytes(log_receipt["blockHash"])
        )

        with self.assertRaises(EthereumBlock.DoesNotExist):
            self.erc20_events_indexer.process_elements(log_receipt_mock)

        # Events were not marked as processed, so they will be retried
        self.assertEqual(
            len(
                self.erc20_events_indexer._filter_not_processed_log_receipts(
                    log_receipt_mock
                )
            ),
            1,
        )

        # The stale block must be flagged, so `check_reorgs_task` can
        # detect the reorg, delete the block (cascading to the tx) and
        # trigger reindexing
        stale_block.refresh_from_db()
        self.assertFalse(stale_block.confirmed)

    def test_events_to_transfer_annotates_safe_membership(self):
        indexer = self.erc20_events_indexer

        # Block/tx must exist so `from_decoded_event` can resolve the timestamp
        for log_receipt in log_receipt_mock:
            EthereumTxFactory(
                tx_hash=log_receipt["transactionHash"],
                block__block_hash=log_receipt["blockHash"],
            )

        # Without a populated address cache (e.g. when reindexing) membership is
        # loaded from database, where no Safe is stored yet
        indexer.addresses_cache = None
        (transfer,) = list(indexer.events_to_erc20_transfer(log_receipt_mock))
        self.assertFalse(transfer._to_is_a_safe)
        self.assertFalse(transfer._from_is_a_safe)

        # With the recipient stored as a Safe, membership loaded from database detects it
        SafeContractFactory(address=transfer.to)
        indexer.addresses_cache = None
        (transfer,) = list(indexer.events_to_erc20_transfer(log_receipt_mock))
        self.assertTrue(transfer._to_is_a_safe)
        self.assertFalse(transfer._from_is_a_safe)

        # With only the recipient tracked: incoming side is a Safe, outgoing side is not.
        indexer.addresses_cache = AddressesCache({transfer.to}, None)
        (transfer,) = list(indexer.events_to_erc20_transfer(log_receipt_mock))
        self.assertTrue(transfer._to_is_a_safe)
        self.assertFalse(transfer._from_is_a_safe)

        # With only the sender tracked: outgoing side is a Safe, incoming side is not.
        indexer.addresses_cache = AddressesCache({transfer._from}, None)
        (transfer,) = list(indexer.events_to_erc20_transfer(log_receipt_mock))
        self.assertFalse(transfer._to_is_a_safe)
        self.assertTrue(transfer._from_is_a_safe)

    def test_get_almost_updated_addresses(self):
        self.assertIsNone(self.erc20_events_indexer.addresses_cache)
        self.assertEqual(
            self.erc20_events_indexer.get_almost_updated_addresses(0), set()
        )
        self.assertIsNone(self.erc20_events_indexer.addresses_cache)

        safe_contract_1 = SafeContractFactory()
        safe_contract_2 = SafeContractFactory()
        self.assertGreaterEqual(safe_contract_2.created, safe_contract_1.created)

        expected_addresses = {safe_contract_1.address, safe_contract_2.address}
        self.assertEqual(
            self.erc20_events_indexer.get_almost_updated_addresses(0),
            expected_addresses,
        )
        self.assertIsNotNone(self.erc20_events_indexer.addresses_cache)
        self.assertEqual(
            self.erc20_events_indexer.addresses_cache.last_checked,
            safe_contract_2.created,
        )
        self.assertEqual(
            self.erc20_events_indexer.addresses_cache.addresses, expected_addresses
        )

        # Add a new address to the database
        safe_contract_3 = SafeContractFactory()
        self.assertGreater(safe_contract_3.created, safe_contract_2.created)

        expected_addresses.add(safe_contract_3.address)
        self.assertEqual(
            self.erc20_events_indexer.get_almost_updated_addresses(0),
            expected_addresses,
        )
        self.assertIsNotNone(self.erc20_events_indexer.addresses_cache)
        self.assertEqual(
            self.erc20_events_indexer.addresses_cache.last_checked,
            safe_contract_3.created,
        )
        self.assertEqual(
            self.erc20_events_indexer.addresses_cache.addresses, expected_addresses
        )

        # Calling the function again, without adding a new address to the DB, should yield the same results
        self.assertEqual(
            self.erc20_events_indexer.get_almost_updated_addresses(0),
            expected_addresses,
        )
        self.assertIsNotNone(self.erc20_events_indexer.addresses_cache)
        self.assertEqual(
            self.erc20_events_indexer.addresses_cache.last_checked,
            safe_contract_3.created,
        )
        self.assertEqual(
            self.erc20_events_indexer.addresses_cache.addresses, expected_addresses
        )
