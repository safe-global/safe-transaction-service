from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from safe_eth.safe import SafeOperationEnum

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
        MultisigTransactionFactory(
            safe=safe_address, nonce=multisig_transaction.nonce, ethereum_tx=None
        )
        self.assertEqual(relevant_queryset.count(), 1)
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        self.assertEqual(relevant_queryset.count(), 2)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        self.assertEqual(relevant_queryset.count(), 3)
        InternalTxFactory(_from=safe_address, value=5)  # Should not appear
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
        MultisigTransactionFactory(
            safe=safe_address,
            ethereum_tx__block__timestamp=timezone.now() - timedelta(days=1),
        )
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        InternalTxFactory(to=safe_address, value=4)
        InternalTxFactory(_from=safe_address, value=5)
        ERC20TransferFactory(to=safe_address)
        ERC20TransferFactory(_from=safe_address)
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        (MultisigTransactionFactory())  # Should not appear, it's for another Safe

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
            all_txs, tx_types, numbers_of_transfers, strict=False
        ):
            self.assertEqual(type(tx), tx_type)
            self.assertEqual(len(tx.transfers), number_of_transfers)
            for transfer in tx.transfers:
                self.assertIsNone(transfer["token"])

        # Insert 2 transfers for the MultisigTx and one for the ModuleTx
        InternalTxFactory(
            _from=safe_address,
            value=5,
            ethereum_tx=another_multisig_transaction.ethereum_tx,
        )
        ERC20TransferFactory(
            to=safe_address, ethereum_tx=another_multisig_transaction.ethereum_tx
        )
        InternalTxFactory(
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
            all_txs_2, tx_types, numbers_of_transfers, strict=False
        ):
            self.assertEqual(type(tx), tx_type)
            self.assertEqual(len(tx.transfers), number_of_transfers)
            for transfer in tx.transfers:
                self.assertIsNone(transfer["token"])

        all_txs_serialized = transaction_service.serialize_all_txs(all_txs_2)
        self.assertEqual(len(all_txs_serialized), len(all_txs_2))
        for tx_serialized in all_txs_serialized:
            self.assertTrue(isinstance(tx_serialized, dict))

    def test_multisend_native_transfers_enriched_when_no_traces(self):
        """
        When a multiSend tx has no indexed native transfers (e.g. chain without
        tracing like Berachain/Scroll), synthetic ETHER_TRANSFER entries are
        built from decoded batch data (issue #2764).
        """
        transaction_service: TransactionService = self.transaction_service
        safe_address = Account.create().address
        # MultiSend v1.3.0 address (DELEGATE_CALL)
        multisend_address = "0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761"
        MultisigTransactionFactory(
            safe=safe_address,
            to=multisend_address,
            operation=SafeOperationEnum.DELEGATE_CALL.value,
            data=b"\x8d\x80\xff\x0a\x00\x00",  # multiSend selector + payload stub
        )
        # No InternalTx ether transfers for this tx (simulates chain without tracing)
        queryset = transaction_service.get_all_tx_identifiers(safe_address)
        all_tx_hashes = [q.ethereum_tx_id for q in queryset]
        decoded_native = [
            {
                "operation": 0,
                "value": "100000000000000",
                "to": "0x3B747C372C2088963ABc2194B7D5ADe238965b33",
                "data": None,
            },
            {
                "operation": 0,
                "value": "200000000000000",
                "to": "0x3B747C372C2088963ABc2194B7D5ADe238965b33",
                "data": None,
            },
        ]
        with mock.patch(
            "safe_transaction_service.history.services.transaction_service.get_tx_decoder"
        ) as get_decoder:
            get_decoder.return_value.decode_multisend_data.return_value = decoded_native
            all_txs = transaction_service.get_all_txs_from_identifiers(
                safe_address, all_tx_hashes
            )
        multisig_txs = [t for t in all_txs if isinstance(t, MultisigTransaction)]
        self.assertEqual(len(multisig_txs), 1)
        tx = multisig_txs[0]
        self.assertEqual(tx.safe, safe_address)
        self.assertEqual(len(tx.transfers), 2)
        for i, transfer in enumerate(tx.transfers):
            self.assertIsNone(transfer.get("token_address"))
            self.assertEqual(transfer["_from"], safe_address)
            self.assertEqual(
                transfer["to"], "0x3B747C372C2088963ABc2194B7D5ADe238965b33"
            )
            self.assertEqual(transfer["_value"], [100000000000000, 200000000000000][i])
            self.assertIn("execution_date", transfer)
            self.assertEqual(transfer["_trace_address"], str(i))
