from django.test import TestCase

from eth_account import Account

from ..models import EthereumTx, ModuleTransaction, MultisigTransaction
from ..services.transaction_service import (TransactionService,
                                            TransactionServiceProvider)
from .factories import (EthereumEventFactory, InternalTxFactory,
                        ModuleTransactionFactory, MultisigTransactionFactory)


class TestTransactionService(TestCase):
    def test_get_all_tx_hashes(self):
        transaction_service: TransactionService = TransactionServiceProvider()
        safe_address = Account.create().address
        self.assertFalse(transaction_service.get_all_tx_hashes(safe_address))

        # Factories create the models using current datetime, so as the txs are returned sorted they should be
        # in the reverse order that they were created
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        multisig_transaction_not_mined = MultisigTransactionFactory(safe=safe_address, nonce=multisig_transaction.nonce,
                                                                    ethereum_tx=None)
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        internal_tx_out = InternalTxFactory(_from=safe_address, value=5)  # Should not appear
        erc20_transfer_in = EthereumEventFactory(to=safe_address)
        erc20_transfer_out = EthereumEventFactory(from_=safe_address)  # Should not appear
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        another_safe_multisig_transaction = MultisigTransactionFactory()  # Should not appear, it's for another Safe

        # Should not appear, nonce > last mined transaction
        higher_nonce_safe_multisig_transaction = MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        higher_nonce_safe_multisig_transaction_2 = MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)

        queryset = transaction_service.get_all_tx_hashes(safe_address)
        all_executed_time = [element['execution_date'] for element in queryset]
        expected_times = [
            another_multisig_transaction.ethereum_tx.block.timestamp,
            erc20_transfer_in.ethereum_tx.block.timestamp,
            internal_tx_in.ethereum_tx.block.timestamp,
            module_transaction.internal_tx.ethereum_tx.block.timestamp,
            multisig_transaction.ethereum_tx.block.timestamp,  # Should take timestamp from tx with same nonce and mined
            multisig_transaction.ethereum_tx.block.timestamp,
        ]
        self.assertEqual(all_executed_time, expected_times)

        all_tx_hashes = list(queryset.values_list('safe_tx_hash', flat=True))
        expected_hashes = [another_multisig_transaction.safe_tx_hash,
                           erc20_transfer_in.ethereum_tx_id,
                           internal_tx_in.ethereum_tx_id,
                           module_transaction.internal_tx.ethereum_tx_id,
                           multisig_transaction.safe_tx_hash,  # First the mined tx
                           multisig_transaction_not_mined.safe_tx_hash]
        self.assertEqual(all_tx_hashes, expected_hashes)

    def test_get_all_txs_from_hashes(self):
        transaction_service: TransactionService = TransactionServiceProvider()
        safe_address = Account.create().address
        self.assertFalse(transaction_service.get_all_tx_hashes(safe_address))

        # Factories create the models using current datetime, so as the txs are returned sorted they should be
        # in the reverse order that they were created
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        internal_tx_out = InternalTxFactory(_from=safe_address, value=5)  # Should not appear
        erc20_transfer_in = EthereumEventFactory(to=safe_address)
        erc20_transfer_out = EthereumEventFactory(from_=safe_address)  # Should not appear
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        another_safe_multisig_transaction = MultisigTransactionFactory()  # Should not appear, it's for another Safe

        all_tx_hashes = list(transaction_service.get_all_tx_hashes(safe_address).values_list('safe_tx_hash',
                                                                                             flat=True))
        all_txs = transaction_service.get_all_txs_from_hashes(safe_address, all_tx_hashes)
        self.assertEqual(len(all_txs), 5)
        tx_types = [MultisigTransaction, EthereumTx, EthereumTx, ModuleTransaction, MultisigTransaction]
        numbers_of_transfers = [0, 1, 1, 0, 0]
        for tx, tx_type, number_of_transfers in zip(all_txs, tx_types, numbers_of_transfers):
            self.assertEqual(type(tx), tx_type)
            self.assertEqual(len(tx.transfers), number_of_transfers)

        # Insert 2 transfers for the MultisigTx and one for the ModuleTx
        internal_tx_out_2 = InternalTxFactory(_from=safe_address, value=5,
                                              ethereum_tx=another_multisig_transaction.ethereum_tx)
        erc20_transfer_in_2 = EthereumEventFactory(to=safe_address,
                                                   ethereum_tx=another_multisig_transaction.ethereum_tx)
        internal_tx_in_2 = InternalTxFactory(to=safe_address, value=4,
                                             ethereum_tx=module_transaction.internal_tx.ethereum_tx)

        all_tx_hashes_2 = list(transaction_service.get_all_tx_hashes(safe_address).values_list('safe_tx_hash',
                                                                                               flat=True))
        all_txs_2 = transaction_service.get_all_txs_from_hashes(safe_address, all_tx_hashes_2)
        self.assertEqual(len(all_txs_2), 5)
        tx_types = [MultisigTransaction, EthereumTx, EthereumTx, ModuleTransaction, MultisigTransaction]
        numbers_of_transfers = [0 + 2, 1, 1, 0 + 1, 0]
        for tx, tx_type, number_of_transfers in zip(all_txs_2, tx_types, numbers_of_transfers):
            self.assertEqual(type(tx), tx_type)
            self.assertEqual(len(tx.transfers), number_of_transfers)

        all_txs_serialized = transaction_service.serialize_all_txs(all_txs_2)
        self.assertEqual(len(all_txs_serialized), len(all_txs_2))
        for tx_serialized in all_txs_serialized:
            self.assertTrue(isinstance(tx_serialized, dict))
