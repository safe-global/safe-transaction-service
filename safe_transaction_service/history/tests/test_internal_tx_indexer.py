from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.test import TestCase

from gnosis.eth import EthereumClient
from gnosis.eth.ethereum_client import ParityManager

from ..indexers import InternalTxIndexerProvider
from ..indexers.tx_processor import SafeTxProcessor, TxProcessor
from ..models import (EthereumBlock, EthereumTx, InternalTx, InternalTxDecoded,
                      SafeContract, SafeMasterCopy, SafeStatus)
from .factories import SafeMasterCopyFactory
from .mocks_internal_tx_indexer import (block_result, trace_filter_result,
                                        trace_transactions_result,
                                        transaction_receipts_result,
                                        transactions_result)


class TestInternalTxIndexer(TestCase):
    @mock.patch.object(ParityManager, 'trace_transactions', autospec=True, return_value=trace_transactions_result)
    @mock.patch.object(ParityManager, 'trace_filter', autospec=True, return_value=trace_filter_result)
    @mock.patch.object(EthereumClient, 'get_blocks', autospec=True, return_value=block_result)
    @mock.patch.object(EthereumClient, 'get_transaction_receipts', autospec=True,
                       return_value=transaction_receipts_result)
    @mock.patch.object(EthereumClient, 'get_transactions', autospec=True, return_value=transactions_result)
    @mock.patch.object(EthereumClient, 'current_block_number', new_callable=PropertyMock)
    def test_internal_tx_indexer(self, current_block_number_mock: MagicMock, transactions_mock: MagicMock,
                                 transaction_receipts_mock: MagicMock, blocks_mock: MagicMock,
                                 trace_filter_mock: MagicMock, trace_transactions_mock: MagicMock):
        current_block_number = 2000
        current_block_number_mock.return_value = current_block_number

        internal_tx_indexer = InternalTxIndexerProvider()
        self.assertEqual(internal_tx_indexer.ethereum_client.current_block_number, current_block_number)
        self.assertIsNone(current_block_number_mock.assert_called_with())

        internal_tx_indexer.start()

        safe_master_copy: SafeMasterCopy = SafeMasterCopyFactory()
        self.assertEqual(safe_master_copy.tx_block_number, 0)
        internal_tx_indexer.start()

        self.assertEqual(EthereumTx.objects.count(), len(transactions_result))
        self.assertEqual(EthereumBlock.objects.count(), len(block_result))
        self.assertEqual(InternalTx.objects.count(), len([y for x in trace_transactions_result for y in x]))
        self.assertEqual(InternalTxDecoded.objects.count(), 2)
        create_internal_tx = InternalTx.objects.get(contract_address='0x673Fd582FED2CD8201d58552B912F0D1DaA37bB2')
        self.assertFalse(create_internal_tx.is_call)
        self.assertFalse(create_internal_tx.is_delegate_call)
        self.assertTrue(create_internal_tx.is_create)

        ethereum_tx = EthereumTx.objects.get(
            tx_hash='0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea')
        self.assertEqual(ethereum_tx.block.number, 6045252)
        self.assertEqual(ethereum_tx.block.block_hash,
                         '0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923')
        self.assertEqual(len(ethereum_tx.logs), 1)

        ethereum_tx = EthereumTx.objects.get(
            tx_hash='0xf554b52dcb336b83bf31e7e2e7aa94853a456f01a139a6b7dec71329460dfb61')
        self.assertEqual(ethereum_tx.block.number, 6045275)
        self.assertEqual(ethereum_tx.block.block_hash,
                         '0x08df561efd3d242263d8a117e32c1beb08454c87df0a287cf93fa39f0675cf04')
        self.assertEqual(ethereum_tx.logs, [])

    def test_tx_processor(self):
        self.test_internal_tx_indexer()
        tx_processor: TxProcessor = SafeTxProcessor()
        self.assertEqual(InternalTxDecoded.objects.count(), 2)  # Setup and execute tx
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(len(internal_txs_decoded), 1)  # Safe not indexed yet
        number_processed = tx_processor.process_decoded_transactions(internal_txs_decoded)  # Index using `setup` trace
        self.assertEqual(len(number_processed), 1)  # Setup trace
        self.assertEqual(SafeContract.objects.count(), 1)

        safe_status = SafeStatus.objects.first()
        self.assertEqual(len(safe_status.owners), 1)
        self.assertEqual(safe_status.nonce, 0)
        self.assertEqual(safe_status.threshold, 1)

        # Decode again now that Safe is indexed (with `setup` call)
        internal_txs_decoded = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(len(internal_txs_decoded), 1)  # Safe indexed, execute tx can be decoded now
        number_processed = tx_processor.process_decoded_transactions(internal_txs_decoded)
        self.assertEqual(len(number_processed), 1)  # Setup trace
        safe_status = SafeStatus.objects.get(nonce=1)
        self.assertEqual(len(safe_status.owners), 1)
        self.assertEqual(safe_status.threshold, 1)
