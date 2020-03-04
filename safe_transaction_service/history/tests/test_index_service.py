from django.test import TestCase

from eth_account import Account
from web3 import Web3

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..models import EthereumTx, MultisigTransaction, SafeStatus
from ..services.index_service import (EthereumBlockHashMismatch, IndexService,
                                      IndexServiceProvider,
                                      TransactionNotFoundException)
from .factories import (EthereumTxFactory, MultisigTransactionFactory,
                        SafeStatusFactory)


class TestIndexService(EthereumTestCaseMixin, TestCase):
    def test_create_or_update_from_tx_hashes_existing(self):
        index_service: IndexService = IndexServiceProvider()
        self.assertListEqual(index_service.txs_create_or_update_from_tx_hashes([]), [])
        tx_hashes = ['0x52fcb05f2ad209d53d84b0a9a7ce6474ab415db88bc364c088758d70c8b5b0ef']
        with self.assertRaisesMessage(TransactionNotFoundException, tx_hashes[0]):
            index_service.txs_create_or_update_from_tx_hashes(tx_hashes)

        # Test with database txs. Use block_number > current_block_number to prevent storing blocks with wrong
        # hashes that will be indexed by next tests
        current_block_number = self.ethereum_client.current_block_number
        ethereum_txs = [EthereumTxFactory(block__number=current_block_number + 100 + i) for i in range(4)]
        tx_hashes = [ethereum_tx.tx_hash for ethereum_tx in ethereum_txs]
        db_txs = index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        self.assertEqual(len(db_txs), len(tx_hashes))
        for db_tx in db_txs:
            self.assertIsNotNone(db_tx)

        # Test with real txs
        value = 6
        real_tx_hashes = [self.send_ether(Account.create().address, value) for _ in range(2)]
        ethereum_txs = index_service.txs_create_or_update_from_tx_hashes(real_tx_hashes)
        self.assertEqual(len(ethereum_txs), len(ethereum_txs))
        for ethereum_tx in ethereum_txs:
            self.assertEqual(ethereum_tx.value, value)

        # Remove blocks and try again
        EthereumTx.objects.filter(tx_hash__in=real_tx_hashes).update(block=None)
        ethereum_txs = index_service.txs_create_or_update_from_tx_hashes(real_tx_hashes)
        for ethereum_tx in ethereum_txs:
            self.assertIsNotNone(ethereum_tx.block)

        # Test mixed
        tx_hashes = tx_hashes + real_tx_hashes
        mixed_txs = index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        self.assertEqual(len(mixed_txs), len(tx_hashes))
        for mixed_tx in mixed_txs:
            self.assertIsNotNone(mixed_tx)

        # Test block hash changes
        ethereum_tx = ethereum_txs[0]
        ethereum_tx.block.block_hash = Web3.keccak(text='aloha')
        ethereum_tx.block.save(update_fields=['block_hash'])
        tx_hash = ethereum_tx.tx_hash

        # Uses database
        index_service.txs_create_or_update_from_tx_hashes([tx_hash])
        ethereum_tx.delete()

        # Try to fetch again
        with self.assertRaises(EthereumBlockHashMismatch):
            index_service.txs_create_or_update_from_tx_hashes([tx_hash])

    def test_reindex_addresses(self):
        index_service: IndexService = IndexServiceProvider()
        self.assertIsNone(index_service.reindex_addresses([]))

        safe_status = SafeStatusFactory()
        MultisigTransactionFactory()  # It shouldn't be deleted
        MultisigTransactionFactory(safe=safe_status.address)  # It should be deleted
        MultisigTransactionFactory(safe=safe_status.address, ethereum_tx=None)  # It shouldn't be deleted
        self.assertIsNone(index_service.reindex_addresses([safe_status.address]))
        self.assertEqual(SafeStatus.objects.count(), 0)
        self.assertEqual(MultisigTransaction.objects.count(), 2)

    def test_reindex_all(self):
        index_service: IndexService = IndexServiceProvider()
        for _ in range(5):
            safe_status = SafeStatusFactory()
            MultisigTransactionFactory(safe=safe_status.address)
        MultisigTransactionFactory(ethereum_tx=None)  # It should be deleted

        self.assertIsNone(index_service.reindex_all())
        self.assertEqual(SafeStatus.objects.count(), 0)
        self.assertEqual(MultisigTransaction.objects.count(), 1)
