from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from eth_account import Account

from ..models import (
    EthereumTx,
    ModuleTransaction,
    MultisigTransaction,
    SafeRelevantTransaction,
)
from ..services.transaction_service import (
    TransactionService,
    TransactionServiceProvider,
)
from .factories import (
    ERC20TransferFactory,
    InternalTxFactory,
    ModuleTransactionFactory,
    MultisigTransactionFactory,
)


class TestTransactionService(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.transaction_service: TransactionService = TransactionServiceProvider()
        cls.transaction_service.redis.flushall()

    def tearDown(self):
        super().tearDown()
        self.transaction_service.redis.flushall()

    def test_get_all_tx_identifiers(self):
        transaction_service: TransactionService = self.transaction_service
        safe_address = Account.create().address
        relevant_queryset = SafeRelevantTransaction.objects.filter(safe=safe_address)
        self.assertFalse(transaction_service.get_all_tx_identifiers(safe_address))

        # Factories create the models using current datetime, so as the txs are returned
        # sorted they should be in the reverse order that they were created
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        self.assertEqual(relevant_queryset.count(), 1)
        multisig_transaction_not_mined = MultisigTransactionFactory(
            safe=safe_address, nonce=multisig_transaction.nonce, ethereum_tx=None
        )
        self.assertEqual(relevant_queryset.count(), 1)
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        self.assertEqual(relevant_queryset.count(), 2)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        self.assertEqual(relevant_queryset.count(), 3)
        internal_tx_out = InternalTxFactory(
            _from=safe_address, value=5
        )  # Should not appear
        self.assertEqual(relevant_queryset.count(), 3)
        erc20_transfer_in = ERC20TransferFactory(to=safe_address)
        self.assertEqual(relevant_queryset.count(), 4)
        erc20_transfer_out = ERC20TransferFactory(_from=safe_address)
        self.assertEqual(relevant_queryset.count(), 5)
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        self.assertEqual(relevant_queryset.count(), 6)
        MultisigTransactionFactory()  # Should not appear, it's for another Safe
        self.assertEqual(relevant_queryset.count(), 6)

        # Just module txs and transfers are returned
        queryset = transaction_service.get_all_tx_identifiers(safe_address)
        self.assertEqual(queryset.count(), 6)

        all_tx_hashes = [element.ethereum_tx_id for element in queryset]
        expected_hashes = [
            another_multisig_transaction.ethereum_tx_id,
            erc20_transfer_out.ethereum_tx_id,
            erc20_transfer_in.ethereum_tx_id,
            internal_tx_in.ethereum_tx_id,
            module_transaction.internal_tx.ethereum_tx_id,
            multisig_transaction.ethereum_tx_id,
        ]
        self.assertListEqual(all_tx_hashes, expected_hashes)

        every_execution_date = [element.timestamp for element in queryset]
        expected_times = [
            another_multisig_transaction.ethereum_tx.block.timestamp,
            erc20_transfer_out.ethereum_tx.block.timestamp,
            erc20_transfer_in.ethereum_tx.block.timestamp,
            internal_tx_in.ethereum_tx.block.timestamp,
            module_transaction.internal_tx.ethereum_tx.block.timestamp,
            multisig_transaction.ethereum_tx.block.timestamp,
        ]
        self.assertListEqual(every_execution_date, expected_times)

    def test_get_all_tx_identifiers_executed(self):
        transaction_service: TransactionService = self.transaction_service
        safe_address = Account.create().address

        # No mined
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        self.assertEqual(
            transaction_service.get_all_tx_identifiers(safe_address).count(),
            0,
        )
        # Mine tx with higher nonce, only that one is executed
        MultisigTransactionFactory(safe=safe_address)
        self.assertEqual(
            transaction_service.get_all_tx_identifiers(safe_address).count(),
            1,
        )

    def test_get_all_txs_from_identifiers(self):
        transaction_service: TransactionService = self.transaction_service
        safe_address = Account.create().address
        self.assertFalse(transaction_service.get_all_tx_identifiers(safe_address))

        # Factories create the models using current datetime, so as the txs are returned sorted they should be
        # in the reverse order that they were created
        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address,
            ethereum_tx__block__timestamp=timezone.now() - timedelta(days=1),
        )
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        internal_tx_out = InternalTxFactory(_from=safe_address, value=5)
        erc20_transfer_in = ERC20TransferFactory(to=safe_address)
        erc20_transfer_out = ERC20TransferFactory(_from=safe_address)
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        another_safe_multisig_transaction = (
            MultisigTransactionFactory()
        )  # Should not appear, it's for another Safe

        queryset = transaction_service.get_all_tx_identifiers(safe_address)
        all_tx_hashes = [q.ethereum_tx_id for q in queryset]

        self.assertEqual(len(self.transaction_service.redis.keys("tx-service:*")), 0)
        all_txs = transaction_service.get_all_txs_from_identifiers(
            safe_address, all_tx_hashes
        )
        self.assertEqual(len(self.transaction_service.redis.keys("tx-service:*")), 1)
        all_txs = transaction_service.get_all_txs_from_identifiers(
            safe_address, all_tx_hashes
        )  # Force caching
        self.assertEqual(len(self.transaction_service.redis.keys("tx-service:*")), 1)
        self.assertEqual(len(all_txs), 6)
        tx_types = [
            MultisigTransaction,
            EthereumTx,
            EthereumTx,
            EthereumTx,
            ModuleTransaction,
            MultisigTransaction,
        ]
        numbers_of_transfers = [0, 1, 1, 1, 0, 0]
        for tx, tx_type, number_of_transfers in zip(
            all_txs, tx_types, numbers_of_transfers
        ):
            self.assertEqual(type(tx), tx_type)
            self.assertEqual(len(tx.transfers), number_of_transfers)
            for transfer in tx.transfers:
                self.assertIsNone(transfer["token"])

        # Insert 2 transfers for the MultisigTx and one for the ModuleTx
        internal_tx_out_2 = InternalTxFactory(
            _from=safe_address,
            value=5,
            ethereum_tx=another_multisig_transaction.ethereum_tx,
        )
        erc20_transfer_in_2 = ERC20TransferFactory(
            to=safe_address, ethereum_tx=another_multisig_transaction.ethereum_tx
        )
        internal_tx_in_2 = InternalTxFactory(
            to=safe_address,
            value=4,
            ethereum_tx=module_transaction.internal_tx.ethereum_tx,
        )

        queryset_2 = transaction_service.get_all_tx_identifiers(safe_address)
        all_tx_hashes_2 = [q.ethereum_tx_id for q in queryset_2]

        all_txs_2 = transaction_service.get_all_txs_from_identifiers(
            safe_address, all_tx_hashes_2
        )
        self.assertEqual(len(all_txs_2), 6)
        tx_types = [
            MultisigTransaction,
            EthereumTx,
            EthereumTx,
            EthereumTx,
            ModuleTransaction,
            MultisigTransaction,
        ]
        numbers_of_transfers = [0 + 2, 1, 1, 1, 0 + 1, 0]
        for tx, tx_type, number_of_transfers in zip(
            all_txs_2, tx_types, numbers_of_transfers
        ):
            self.assertEqual(type(tx), tx_type)
            self.assertEqual(len(tx.transfers), number_of_transfers)
            for transfer in tx.transfers:
                self.assertIsNone(transfer["token"])

        all_txs_serialized = transaction_service.serialize_all_txs(all_txs_2)
        self.assertEqual(len(all_txs_serialized), len(all_txs_2))
        for tx_serialized in all_txs_serialized:
            self.assertTrue(isinstance(tx_serialized, dict))
