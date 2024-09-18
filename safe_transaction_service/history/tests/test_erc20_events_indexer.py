from django.test import TestCase

from safe_eth.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..indexers import Erc20EventsIndexerProvider
from ..models import ERC20Transfer, EthereumTx, IndexingStatus, SafeRelevantTransaction
from .factories import EthereumTxFactory, SafeContractFactory
from .mocks.mocks_erc20_events_indexer import log_receipt_mock


class TestErc20EventsIndexer(EthereumTestCaseMixin, TestCase):
    def setUp(self) -> None:
        Erc20EventsIndexerProvider.del_singleton()
        self.erc20_events_indexer = Erc20EventsIndexerProvider()

    def tearDown(self) -> None:
        Erc20EventsIndexerProvider.del_singleton()

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
        processed_element_cache = (
            self.erc20_events_indexer.element_already_processed_checker._processed_element_cache
        )
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
