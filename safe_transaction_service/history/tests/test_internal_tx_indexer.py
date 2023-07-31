import itertools
from collections import OrderedDict
from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.test import TestCase

from eth_typing import HexStr

from gnosis.eth import EthereumClient
from gnosis.eth.ethereum_client import TracingManager

from ..indexers import InternalTxIndexer, InternalTxIndexerProvider
from ..indexers.internal_tx_indexer import InternalTxIndexerWithTraceBlock
from ..indexers.tx_processor import SafeTxProcessorProvider
from ..models import (
    EthereumBlock,
    EthereumTx,
    IndexingStatus,
    InternalTx,
    InternalTxDecoded,
    SafeContract,
    SafeLastStatus,
    SafeMasterCopy,
    SafeStatus,
)
from .factories import EthereumTxFactory, SafeMasterCopyFactory
from .mocks.mocks_internal_tx_indexer import (
    block_result,
    trace_blocks_filtered_0x5aC2_result,
    trace_blocks_result,
    trace_filter_result,
    trace_transactions_result,
    transaction_receipts_result,
    transactions_result,
)


class TestInternalTxIndexer(TestCase):
    def setUp(self) -> None:
        InternalTxIndexerProvider.del_singleton()
        self.internal_tx_indexer = InternalTxIndexerProvider()
        self.internal_tx_indexer.blocks_to_reindex_again = 0

    def tearDown(self) -> None:
        InternalTxIndexerProvider.del_singleton()

    def test_internal_tx_indexer_provider(self):
        internal_tx_indexer = InternalTxIndexerProvider()
        self.assertIsInstance(internal_tx_indexer, InternalTxIndexer)
        self.assertNotIsInstance(internal_tx_indexer, InternalTxIndexerWithTraceBlock)
        InternalTxIndexerProvider.del_singleton()
        with self.settings(ETH_INTERNAL_NO_FILTER=True):
            internal_tx_indexer = InternalTxIndexerProvider()
            self.assertIsInstance(
                internal_tx_indexer,
                (InternalTxIndexer, InternalTxIndexerWithTraceBlock),
            )

    def return_sorted_blocks(self, hashes: HexStr):
        """
        Mock function helper

        :param hashes:
        :return:
        """
        block_dict = {block["hash"].hex(): block for block in block_result}
        return [block_dict[provided_hash] for provided_hash in hashes]

    @mock.patch.object(
        TracingManager, "trace_blocks", autospec=True, return_value=trace_blocks_result
    )
    @mock.patch.object(
        TracingManager, "trace_filter", autospec=True, return_value=trace_filter_result
    )
    @mock.patch.object(
        TracingManager,
        "trace_transactions",
        autospec=True,
        return_value=trace_transactions_result,
    )
    @mock.patch.object(
        EthereumClient, "get_blocks", autospec=True, side_effect=return_sorted_blocks
    )
    @mock.patch.object(
        EthereumClient,
        "get_transaction_receipts",
        autospec=True,
        return_value=transaction_receipts_result,
    )
    @mock.patch.object(
        EthereumClient,
        "get_transactions",
        autospec=True,
        return_value=transactions_result,
    )
    @mock.patch.object(
        EthereumClient,
        "current_block_number",
        new_callable=PropertyMock,
        return_value=2000,
    )
    def _test_internal_tx_indexer(
        self,
        current_block_number_mock: MagicMock,
        transactions_mock: MagicMock,
        transaction_receipts_mock: MagicMock,
        blocks_mock: MagicMock,
        trace_transactions_mock: MagicMock,
        trace_filter_mock: MagicMock,
        trace_block_mock: MagicMock,
    ):
        current_block_number = current_block_number_mock.return_value

        internal_tx_indexer = self.internal_tx_indexer
        self.assertEqual(
            internal_tx_indexer.ethereum_client.current_block_number,
            current_block_number,
        )
        self.assertIsNone(current_block_number_mock.assert_called_with())

        self.assertEqual(
            internal_tx_indexer.start(), (0, 0)
        )  # No SafeMasterCopy to index

        safe_master_copy: SafeMasterCopy = SafeMasterCopyFactory(
            address="0x5aC255889882aCd3da2aA939679E3f3d4cea221e"
        )
        self.assertEqual(safe_master_copy.tx_block_number, 0)
        self.assertEqual(internal_tx_indexer.start(), (3, 2001))

        self.assertEqual(EthereumTx.objects.count(), len(transactions_result))
        self.assertEqual(EthereumBlock.objects.count(), len(block_result))
        # Just store useful traces 2 decoded + 1 contract creation + 2 ether transfers
        self.assertEqual(InternalTx.objects.count(), 5)
        self.assertEqual(InternalTxDecoded.objects.count(), 2)
        create_internal_tx = InternalTx.objects.get(
            contract_address="0x673Fd582FED2CD8201d58552B912F0D1DaA37bB2"
        )
        self.assertFalse(create_internal_tx.is_call)
        self.assertFalse(create_internal_tx.is_delegate_call)
        self.assertTrue(create_internal_tx.is_create)

        ethereum_tx = EthereumTx.objects.get(
            tx_hash="0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea"
        )
        self.assertEqual(ethereum_tx.block.number, 6045252)
        self.assertEqual(
            ethereum_tx.block.block_hash,
            "0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923",
        )
        self.assertEqual(len(ethereum_tx.logs), 1)

        ethereum_tx = EthereumTx.objects.get(
            tx_hash="0xf554b52dcb336b83bf31e7e2e7aa94853a456f01a139a6b7dec71329460dfb61"
        )
        self.assertEqual(ethereum_tx.block.number, 6045275)
        self.assertEqual(
            ethereum_tx.block.block_hash,
            "0x08df561efd3d242263d8a117e32c1beb08454c87df0a287cf93fa39f0675cf04",
        )
        self.assertEqual(ethereum_tx.logs, [])

        trace_filter_mock.assert_called_once_with(
            internal_tx_indexer.ethereum_client.tracing,
            from_block=0,
            to_block=current_block_number - internal_tx_indexer.number_trace_blocks,
            to_address=[safe_master_copy.address],
        )
        trace_block_mock.assert_called_with(
            internal_tx_indexer.ethereum_client.tracing,
            list(
                range(
                    current_block_number - internal_tx_indexer.number_trace_blocks + 1,
                    current_block_number + 1 - internal_tx_indexer.confirmations,
                )
            ),
        )

    def test_internal_tx_indexer(self):
        self._test_internal_tx_indexer()

    @mock.patch.object(
        TracingManager,
        "trace_blocks",
        autospec=True,
        return_value=trace_blocks_filtered_0x5aC2_result,
    )
    @mock.patch.object(
        TracingManager, "trace_filter", autospec=True, return_value=trace_filter_result
    )
    @mock.patch.object(
        EthereumClient,
        "current_block_number",
        new_callable=PropertyMock,
        return_value=2000,
    )
    def test_find_relevant_elements(
        self,
        current_block_number_mock: MagicMock,
        trace_filter_mock: MagicMock,
        trace_block_mock: MagicMock,
    ):
        current_block_number = current_block_number_mock.return_value
        internal_tx_indexer = self.internal_tx_indexer
        addresses = ["0x5aC255889882aCd3da2aA939679E3f3d4cea221e"]
        trace_filter_transactions = OrderedDict(
            (trace["transactionHash"], []) for trace in trace_filter_mock.return_value
        )
        trace_block_transactions = OrderedDict(
            (
                (k, list(v))
                for k, v in itertools.groupby(
                    itertools.chain(*trace_block_mock.return_value),
                    lambda x: x["transactionHash"],
                )
            )
        )

        # Just trace filter
        elements = internal_tx_indexer.find_relevant_elements(
            addresses, 1, current_block_number - 50
        )
        self.assertEqual(trace_filter_transactions, elements)
        trace_filter_mock.assert_called_once_with(
            internal_tx_indexer.ethereum_client.tracing,
            from_block=1,
            to_block=current_block_number - 50,
            to_address=addresses,
        )
        trace_block_mock.assert_not_called()
        trace_filter_mock.reset_mock()

        # Mixed trace_block and trace_filter
        elements = internal_tx_indexer.find_relevant_elements(
            addresses, current_block_number - 50, current_block_number
        )
        self.assertEqual(trace_filter_transactions | trace_block_transactions, elements)
        trace_filter_mock.assert_called_once_with(
            internal_tx_indexer.ethereum_client.tracing,
            from_block=current_block_number - 50,
            to_block=current_block_number - internal_tx_indexer.number_trace_blocks,
            to_address=addresses,
        )

        trace_block_mock.assert_called_with(
            internal_tx_indexer.ethereum_client.tracing,
            list(
                range(
                    current_block_number - internal_tx_indexer.number_trace_blocks + 1,
                    current_block_number + 1,
                )
            ),
        )

        trace_filter_mock.reset_mock()
        trace_block_mock.reset_mock()

        # Just trace block
        elements = internal_tx_indexer.find_relevant_elements(
            addresses, current_block_number - 3, current_block_number
        )
        self.assertEqual(trace_block_transactions, elements)
        trace_filter_mock.assert_not_called()

        trace_block_mock.assert_called_with(
            internal_tx_indexer.ethereum_client.tracing,
            list(range(current_block_number - 3, current_block_number + 1)),
        )

    def test_tx_processor_using_internal_tx_indexer(self):
        self._test_internal_tx_indexer()
        tx_processor = SafeTxProcessorProvider()
        self.assertEqual(InternalTxDecoded.objects.count(), 2)  # Setup and execute tx
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(len(internal_txs_decoded), 2)
        number_processed = tx_processor.process_decoded_transactions(
            internal_txs_decoded
        )  # Index using `setup` trace
        self.assertEqual(len(number_processed), 2)  # Setup and execute trace
        self.assertEqual(SafeContract.objects.count(), 1)
        self.assertEqual(SafeStatus.objects.count(), 2)

        safe_status = SafeStatus.objects.first()
        self.assertEqual(len(safe_status.owners), 1)
        self.assertEqual(safe_status.nonce, 0)
        self.assertEqual(safe_status.threshold, 1)

        # Try to decode again without new traces, nothing should be decoded
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(
            len(internal_txs_decoded), 0
        )  # Safe indexed, execute tx can be decoded now
        number_processed = tx_processor.process_decoded_transactions(
            internal_txs_decoded
        )
        self.assertEqual(len(number_processed), 0)  # Setup trace
        safe_status = SafeStatus.objects.get(nonce=1)
        self.assertEqual(len(safe_status.owners), 1)
        self.assertEqual(safe_status.threshold, 1)

        safe_last_status = SafeLastStatus.objects.get()
        self.assertEqual(
            safe_last_status, SafeLastStatus.from_status_instance(safe_status)
        )

    def test_tx_processor_using_internal_tx_indexer_with_existing_safe(self):
        self._test_internal_tx_indexer()
        tx_processor = SafeTxProcessorProvider()
        tx_processor.process_decoded_transactions(
            InternalTxDecoded.objects.pending_for_safes()
        )
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 0
        )

        SafeStatus.objects.all().delete()
        InternalTxDecoded.objects.update(processed=False)
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(internal_txs_decoded.count(), 2)
        self.assertEqual(internal_txs_decoded[0].function_name, "setup")
        results = tx_processor.process_decoded_transactions(internal_txs_decoded)
        self.assertEqual(results, [True, True])

    def test_element_already_processed_checker(self):
        """
        Test not reprocessing of processed events
        """

        # Transform mock to dictionary tx_hash -> traces
        tx_hash_with_traces = {}
        for trace_transaction_result in trace_transactions_result:
            tx_hash = trace_transaction_result[0]["transactionHash"]
            tx_hash_with_traces[tx_hash] = trace_transaction_result
            # Create transaction in db so not fetching of transaction is needed
            EthereumTxFactory(tx_hash=tx_hash)

        # After the first processing transactions will be cached to prevent reprocessing
        processed_element_cache = (
            self.internal_tx_indexer.element_already_processed_checker._processed_element_cache
        )
        self.assertEqual(len(processed_element_cache), 0)
        self.assertEqual(
            len(self.internal_tx_indexer.process_elements(tx_hash_with_traces)), 2
        )
        self.assertEqual(len(processed_element_cache), 2)

        # Transactions are cached and will not be reprocessed
        self.assertEqual(
            len(self.internal_tx_indexer.process_elements(tx_hash_with_traces)), 0
        )
        self.assertEqual(
            len(self.internal_tx_indexer.process_elements(tx_hash_with_traces)), 0
        )

        # Cleaning the cache will reprocess the transactions again
        self.internal_tx_indexer.element_already_processed_checker.clear()
        self.assertEqual(
            len(self.internal_tx_indexer.process_elements(tx_hash_with_traces)), 2
        )
