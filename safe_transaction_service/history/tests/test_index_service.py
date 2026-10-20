# SPDX-License-Identifier: FSL-1.1-MIT
import datetime
from unittest import mock
from unittest.mock import PropertyMock

from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from requests.exceptions import ConnectionError as RequestsConnectionError
from safe_eth.eth import EthereumClient
from safe_eth.eth.tests.ethereum_test_case import EthereumTestCaseMixin
from safe_eth.eth.utils import fast_keccak_text

from ..models import (
    EthereumTx,
    IndexingStatus,
    MultisigConfirmation,
    MultisigTransaction,
    SafeLastStatus,
    SafeStatus,
)
from ..services.index_service import (
    IndexService,
    IndexServiceProvider,
    TransactionNotFoundException,
)
from .factories import (
    EthereumBlockFactory,
    EthereumTxFactory,
    InternalTxDecodedFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeMasterCopyFactory,
    SafeStatusFactory,
)


class TestIndexService(EthereumTestCaseMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.index_service = IndexServiceProvider()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        IndexServiceProvider.del_singleton()

    def test_create_or_update_from_tx_hashes_existing(self):
        index_service: IndexService = self.index_service
        self.assertListEqual(index_service.txs_create_or_update_from_tx_hashes([]), [])
        tx_hashes = [
            "0x52fcb05f2ad209d53d84b0a9a7ce6474ab415db88bc364c088758d70c8b5b0ef"
        ]
        with self.assertRaisesMessage(TransactionNotFoundException, tx_hashes[0]):
            index_service.txs_create_or_update_from_tx_hashes(tx_hashes)

        # Test with database txs. Use block_number > current_block_number to prevent storing blocks with wrong
        # hashes that will be indexed by next tests
        current_block_number = self.ethereum_client.current_block_number
        ethereum_txs = [
            EthereumTxFactory(block__number=current_block_number + 100 + i)
            for i in range(4)
        ]
        tx_hashes = [ethereum_tx.tx_hash for ethereum_tx in ethereum_txs]
        db_txs = index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        self.assertEqual(len(db_txs), len(tx_hashes))
        for db_tx in db_txs:
            self.assertIsNotNone(db_tx)

        # Test with real txs
        value = 6
        real_tx_hashes = [
            self.send_ether(Account.create().address, value) for _ in range(2)
        ]
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
        ethereum_tx.block.block_hash = fast_keccak_text("aloha")
        ethereum_tx.block.save(update_fields=["block_hash"])
        tx_hash = ethereum_tx.tx_hash

        # Uses database
        index_service.txs_create_or_update_from_tx_hashes([tx_hash])
        ethereum_tx.delete()

    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_is_service_synced(self, current_block_number_mock: PropertyMock):
        IndexingStatus.objects.set_erc20_721_indexing_status(500)
        current_block_number_mock.return_value = 500
        self.assertTrue(self.index_service.is_service_synced())
        reorg_blocks = self.index_service.eth_reorg_blocks

        safe_master_copy = SafeMasterCopyFactory(
            tx_block_number=current_block_number_mock.return_value - reorg_blocks - 1
        )
        self.assertFalse(self.index_service.is_service_synced())
        safe_master_copy.tx_block_number = safe_master_copy.tx_block_number + 1
        safe_master_copy.save(update_fields=["tx_block_number"])
        self.assertTrue(self.index_service.is_service_synced())

        IndexingStatus.objects.set_erc20_721_indexing_status(
            current_block_number_mock.return_value - reorg_blocks - 1
        )
        self.assertFalse(self.index_service.is_service_synced())
        IndexingStatus.objects.set_erc20_721_indexing_status(
            current_block_number_mock.return_value - reorg_blocks
        )
        self.assertTrue(self.index_service.is_service_synced())

        # Test connection error to the node
        current_block_number_mock.side_effect = RequestsConnectionError
        self.assertFalse(self.index_service.is_service_synced())

    def test_process_decoded_txs_for_safe(self):
        safe_address = Account.create().address
        with mock.patch.object(
            IndexService, "fix_out_of_order"
        ) as fix_out_of_order_mock:
            self.assertEqual(
                self.index_service.process_decoded_txs_for_safe(safe_address), 0
            )
            fix_out_of_order_mock.assert_not_called()

            # Setup for a random Safe should not be processed
            InternalTxDecodedFactory(
                function_name="setup",
            )
            self.assertEqual(
                self.index_service.process_decoded_txs_for_safe(safe_address), 0
            )

            InternalTxDecodedFactory(
                function_name="setup",
                internal_tx___from=safe_address,
            )
            self.assertEqual(
                self.index_service.process_decoded_txs_for_safe(safe_address), 1
            )
            fix_out_of_order_mock.assert_not_called()
            # After processed, it should not be processed again
            self.assertEqual(
                self.index_service.process_decoded_txs_for_safe(safe_address), 0
            )

            exec_transactions = [
                InternalTxDecodedFactory(
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                )
                for _ in range(3)
            ]

            self.assertEqual(
                self.index_service.process_decoded_txs_for_safe(safe_address), 3
            )
            fix_out_of_order_mock.assert_not_called()
            # After processed, they should not be processed again
            self.assertEqual(
                self.index_service.process_decoded_txs_for_safe(safe_address), 0
            )

            # Add a transaction out of order
            exec_transactions[1].processed = False
            exec_transactions[1].save(update_fields=["processed"])
            self.assertEqual(
                self.index_service.process_decoded_txs_for_safe(safe_address), 1
            )
            # Out of order transaction was detected
            fix_out_of_order_mock.assert_called_with(
                safe_address, exec_transactions[1].internal_tx
            )

    def test_reprocess_addresses(self):
        index_service: IndexService = self.index_service
        self.assertIsNone(index_service.reprocess_addresses([]))

        safe_status = SafeStatusFactory()
        SafeLastStatus.objects.get_or_generate(safe_status.address)
        MultisigTransactionFactory()  # It shouldn't be deleted (safe not matching)
        MultisigTransactionFactory(
            safe=safe_status.address, origin={}
        )  # It should be deleted
        MultisigTransactionFactory(
            safe=safe_status.address, ethereum_tx=None
        )  # It shouldn't be deleted
        MultisigTransactionFactory(
            safe=safe_status.address, origin="Something"
        )  # It shouldn't be deleted
        self.assertEqual(MultisigTransaction.objects.count(), 4)
        self.assertIsNone(index_service.reprocess_addresses([safe_status.address]))
        self.assertEqual(SafeStatus.objects.count(), 0)
        self.assertEqual(SafeLastStatus.objects.count(), 0)
        self.assertEqual(MultisigTransaction.objects.count(), 3)

    def test_reprocess_all(self):
        index_service: IndexService = self.index_service
        for _ in range(5):
            safe_status = SafeStatusFactory()
            SafeLastStatus.objects.get_or_generate(safe_status.address)
            MultisigTransactionFactory(safe=safe_status.address, origin={})

        MultisigTransactionFactory(ethereum_tx=None)  # It shouldn't be deleted
        MultisigTransactionFactory(origin="Something")  # It shouldn't be deleted

        self.assertEqual(MultisigTransaction.objects.count(), 7)
        self.assertIsNone(index_service.reprocess_all())
        self.assertEqual(SafeStatus.objects.count(), 0)
        self.assertEqual(SafeLastStatus.objects.count(), 0)
        self.assertEqual(MultisigTransaction.objects.count(), 2)

    def test_fix_out_of_order(self):
        index_service: IndexService = self.index_service

        safe_status = SafeStatusFactory()
        safe_address = safe_status.address
        SafeStatusFactory(address=safe_address)
        safe_status_3 = SafeStatusFactory(address=safe_address)
        SafeStatusFactory(address=safe_address)
        SafeStatusFactory()  # It should not be removed
        SafeLastStatus.objects.get_or_generate(safe_address)
        timestamp = safe_status_3.internal_tx.timestamp
        before = timestamp - datetime.timedelta(minutes=1)
        after = timestamp + datetime.timedelta(minutes=1)

        # Executed before the timestamp, they shouldn't be changed
        multisig_tx_before = MultisigTransactionFactory(
            safe=safe_address, origin={}, ethereum_tx__block__timestamp=before
        )
        multisig_tx_api_before = MultisigTransactionFactory(
            safe=safe_address, ethereum_tx__block__timestamp=before
        )
        # Other Safe, it shouldn't be changed
        multisig_tx_other_safe = MultisigTransactionFactory(
            origin={}, ethereum_tx__block__timestamp=after
        )
        # Not executed, it shouldn't be changed
        multisig_tx_not_executed = MultisigTransactionFactory(
            safe=safe_address, ethereum_tx=None
        )
        # Created by the indexer, it should be deleted
        multisig_tx_indexer = MultisigTransactionFactory(
            safe=safe_address, origin={}, ethereum_tx__block__timestamp=after
        )
        MultisigConfirmationFactory(
            multisig_transaction=multisig_tx_indexer, ethereum_tx=None, created=after
        )
        approve_hash_confirmation = MultisigConfirmationFactory(
            multisig_transaction=multisig_tx_indexer
        )
        # Proposed by a user, it should be unlinked from its ethereum tx
        multisig_tx_api = MultisigTransactionFactory(
            safe=safe_address, ethereum_tx__block__timestamp=after
        )
        # Proposed by a user with no origin, it should be unlinked too
        multisig_tx_api_no_origin = MultisigTransactionFactory(
            safe=safe_address,
            origin={},
            proposer=Account.create().address,
            ethereum_tx__block__timestamp=after,
        )
        api_signature_confirmation = MultisigConfirmationFactory(
            multisig_transaction=multisig_tx_api, ethereum_tx=None
        )
        MultisigConfirmationFactory(
            multisig_transaction=multisig_tx_api, ethereum_tx=None, created=after
        )
        api_approve_hash_confirmation = MultisigConfirmationFactory(
            multisig_transaction=multisig_tx_api
        )
        self.assertEqual(MultisigTransaction.objects.count(), 7)
        self.assertEqual(MultisigConfirmation.objects.count(), 5)
        self.assertEqual(SafeStatus.objects.count(), 5)

        with mock.patch(
            "safe_transaction_service.history.signals._process_event"
        ) as process_event_mock:
            self.assertIsNone(
                index_service.fix_out_of_order(safe_address, safe_status_3.internal_tx)
            )
            process_event_mock.assert_not_called()

        self.assertEqual(SafeStatus.objects.count(), 3)
        self.assertEqual(SafeLastStatus.objects.count(), 0)

        self.assertCountEqual(
            MultisigTransaction.objects.values_list("safe_tx_hash", flat=True),
            [
                multisig_tx_before.safe_tx_hash,
                multisig_tx_api_before.safe_tx_hash,
                multisig_tx_other_safe.safe_tx_hash,
                multisig_tx_not_executed.safe_tx_hash,
                multisig_tx_api.safe_tx_hash,
                multisig_tx_api_no_origin.safe_tx_hash,
            ],
        )
        for multisig_tx in (
            multisig_tx_before,
            multisig_tx_api_before,
            multisig_tx_other_safe,
        ):
            multisig_tx.refresh_from_db()
            self.assertIsNotNone(multisig_tx.ethereum_tx_id)
        for multisig_tx in (multisig_tx_api, multisig_tx_api_no_origin):
            multisig_tx.refresh_from_db()
            self.assertIsNone(multisig_tx.ethereum_tx_id)

        # Confirmations built from the execution signatures are deleted
        self.assertCountEqual(
            MultisigConfirmation.objects.values_list("id", flat=True),
            [
                approve_hash_confirmation.id,
                api_signature_confirmation.id,
                api_approve_hash_confirmation.id,
            ],
        )
        approve_hash_confirmation.refresh_from_db()
        self.assertIsNone(approve_hash_confirmation.multisig_transaction_id)
        api_approve_hash_confirmation.refresh_from_db()
        self.assertEqual(
            api_approve_hash_confirmation.multisig_transaction_id,
            multisig_tx_api.safe_tx_hash,
        )

    def test_fix_out_of_order_late_exec_transaction(self):
        """
        An `execTransaction` indexed after newer ones were processed (e.g. a trace
        missed by the node and found by a reindex) must leave one executed multisig
        transaction per ethereum tx, with the nonces of the chain
        """
        index_service: IndexService = self.index_service
        safe_address = Account.create().address
        now = timezone.now()
        blocks = [
            EthereumBlockFactory(timestamp=now + datetime.timedelta(minutes=i))
            for i in range(4)
        ]
        InternalTxDecodedFactory(
            function_name="setup",
            internal_tx___from=safe_address,
            internal_tx__ethereum_tx__block=blocks[0],
        )
        first_tx = InternalTxDecodedFactory(
            function_name="execTransaction",
            internal_tx___from=safe_address,
            internal_tx__ethereum_tx__block=blocks[1],
        )
        last_tx = InternalTxDecodedFactory(
            function_name="execTransaction",
            internal_tx___from=safe_address,
            internal_tx__ethereum_tx__block=blocks[3],
        )
        self.assertEqual(index_service.process_decoded_txs_for_safe(safe_address), 3)
        # `last_tx` was processed with a wrong nonce
        self.assertEqual(
            MultisigTransaction.objects.get(
                ethereum_tx_id=last_tx.internal_tx.ethereum_tx_id
            ).nonce,
            1,
        )

        # The missing trace is found later
        late_tx = InternalTxDecodedFactory(
            function_name="execTransaction",
            internal_tx___from=safe_address,
            internal_tx__ethereum_tx__block=blocks[2],
        )
        self.assertEqual(index_service.process_decoded_txs_for_safe(safe_address), 2)

        self.assertEqual(
            list(
                MultisigTransaction.objects.filter(safe=safe_address)
                .order_by("nonce")
                .values_list("nonce", "ethereum_tx_id")
            ),
            [
                (0, first_tx.internal_tx.ethereum_tx_id),
                (1, late_tx.internal_tx.ethereum_tx_id),
                (2, last_tx.internal_tx.ethereum_tx_id),
            ],
        )
        self.assertEqual(SafeLastStatus.objects.get(address=safe_address).nonce, 3)
