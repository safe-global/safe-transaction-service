from django.test import TestCase

from eth_account import Account
from hexbytes import HexBytes

from gnosis.eth.constants import NULL_ADDRESS, SENTINEL_ADDRESS
from gnosis.eth.contracts import get_safe_V1_3_0_contract
from gnosis.safe import Safe
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..indexers.safe_events_indexer import (SafeEventsIndexer,
                                            SafeEventsIndexerProvider)
from ..indexers.tx_processor import SafeTxProcessor
from ..models import (EthereumTxCallType, InternalTx, InternalTxDecoded,
                      InternalTxType, MultisigConfirmation,
                      MultisigTransaction, SafeStatus)
from .factories import SafeL2MasterCopyFactory


class TestSafeEventsIndexer(SafeTestCaseMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.safe_events_indexer = SafeEventsIndexer(cls.ethereum_client, confirmations=0)
        cls.safe_tx_processor = SafeTxProcessor(cls.ethereum_client)

    def test_safe_events_indexer_provider(self):
        SafeEventsIndexerProvider()
        self.assertIsNotNone(SafeEventsIndexerProvider.instance)
        SafeEventsIndexerProvider.del_singleton()
        self.assertIsNone(getattr(SafeEventsIndexerProvider, 'instance', None))

    def test_safe_events_indexer(self):
        owner_account_1 = self.ethereum_test_account
        owners = [owner_account_1.address]
        threshold = 1
        to = NULL_ADDRESS
        data = b''
        fallback_handler = NULL_ADDRESS
        payment_token = NULL_ADDRESS
        payment = 0
        payment_receiver = NULL_ADDRESS
        initializer = HexBytes(
            self.safe_contract_V1_3_0.functions.setup(
                owners, threshold, to, data, fallback_handler, payment_token,
                payment, payment_receiver
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )
        block_number = self.ethereum_client.current_block_number
        SafeL2MasterCopyFactory(address=self.safe_contract_V1_3_0.address,
                                initial_block_number=block_number, tx_block_number=block_number, version='1.3.0')
        ethereum_tx_sent = self.proxy_factory.deploy_proxy_contract(
            self.ethereum_test_account, self.safe_contract_V1_3_0.address,
            initializer=initializer
        )
        safe_address = ethereum_tx_sent.contract_address
        safe = Safe(safe_address, self.ethereum_client)
        safe_contract = get_safe_V1_3_0_contract(self.w3, safe_address)
        self.assertEqual(safe_contract.functions.VERSION().call(), '1.3.0')

        self.assertEqual(InternalTx.objects.count(), 0)
        self.assertEqual(InternalTxDecoded.objects.count(), 0)
        self.assertEqual(self.safe_events_indexer.start(), 2)
        self.assertEqual(InternalTxDecoded.objects.count(), 1)
        self.assertEqual(InternalTx.objects.count(), 2)  # Proxy factory and setup
        create_internal_tx = InternalTx.objects.filter(contract_address=safe_address).get()
        setup_internal_tx = InternalTx.objects.filter(contract_address=None).get()

        self.assertEqual(create_internal_tx.trace_address, '1')
        self.assertEqual(create_internal_tx.tx_type, InternalTxType.CREATE.value)
        self.assertIsNone(create_internal_tx.call_type)
        self.assertTrue(create_internal_tx.is_relevant)

        self.assertEqual(setup_internal_tx.trace_address, '1,0')

        txs_decoded_queryset = InternalTxDecoded.objects.pending_for_safes()
        self.assertEqual(SafeStatus.objects.count(), 0)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        self.assertEqual(SafeStatus.objects.count(), 1)
        safe_status = SafeStatus.objects.get()
        self.assertEqual(safe_status.master_copy, self.safe_contract_V1_3_0.address)
        self.assertEqual(safe_status.owners, owners)
        self.assertEqual(safe_status.threshold, threshold)
        self.assertEqual(safe_status.nonce, 0)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertIsNone(safe_status.guard)
        self.assertEqual(MultisigTransaction.objects.count(), 0)
        self.assertEqual(MultisigConfirmation.objects.count(), 0)

        # Add an owner but don't update the threshold (nonce: 0) --------------------------------------------------
        owner_account_2 = Account.create()
        data = HexBytes(
            self.safe_contract_V1_3_0.functions.addOwnerWithThreshold(
                owner_account_2.address,
                1
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, AddedOwner, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.assertEqual(InternalTx.objects.count(), 5)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one adding the owner
        self.assertEqual(SafeStatus.objects.count(), 3)
        safe_status = SafeStatus.objects.last_for_address(safe_address)  # Processed execTransaction and addOwner
        self.assertCountEqual(safe_status.owners, [owner_account_1.address, owner_account_2.address])
        self.assertEqual(safe_status.nonce, 1)

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[1]  # Just processed execTransaction
        self.assertCountEqual(safe_status.owners, [owner_account_1.address])
        self.assertEqual(safe_status.nonce, 1)

        self.assertEqual(MultisigTransaction.objects.count(), 1)
        self.assertEqual(MultisigTransaction.objects.get().safe_tx_hash, multisig_tx.safe_tx_hash.hex())
        self.assertEqual(MultisigConfirmation.objects.count(), 1)

        # Change threshold (nonce: 1) ------------------------------------------------------------------------------
        data = HexBytes(
            self.safe_contract_V1_3_0.functions.changeThreshold(
                2
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ChangedThreshold, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one changing the threshold
        self.assertEqual(SafeStatus.objects.count(), 5)
        safe_status = SafeStatus.objects.last_for_address(safe_address)  # Processed execTransaction and changeThreshold
        self.assertEqual(safe_status.nonce, 2)
        self.assertEqual(safe_status.threshold, 2)

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[1]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 2)
        self.assertEqual(safe_status.threshold, 1)

        self.assertEqual(MultisigTransaction.objects.count(), 2)
        self.assertEqual(MultisigTransaction.objects.order_by('-nonce')[0].safe_tx_hash,
                         multisig_tx.safe_tx_hash.hex())
        self.assertEqual(MultisigConfirmation.objects.count(), 2)

        # Remove an owner and change threshold back to 1 (nonce: 2) --------------------------------------------------
        data = HexBytes(
            self.safe_contract_V1_3_0.functions.removeOwner(
                SENTINEL_ADDRESS,
                owner_account_2.address,
                1
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.sign(owner_account_2.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, RemovedOwner, ChangedThreshold, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 4)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one removing the owner
        self.assertEqual(SafeStatus.objects.count(), 8)
        safe_status = SafeStatus.objects.last_for_address(safe_address)  # Processed execTransaction, removeOwner and changeThreshold
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, 1)
        self.assertEqual(safe_status.owners, [owner_account_1.address])

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[1]  # Processed execTransaction and removeOwner
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, 2)
        self.assertEqual(safe_status.owners, [owner_account_1.address])

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[2]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, 2)
        self.assertCountEqual(safe_status.owners, [owner_account_1.address, owner_account_2.address])

        self.assertEqual(MultisigTransaction.objects.count(), 3)
        self.assertEqual(MultisigTransaction.objects.order_by('-nonce')[0].safe_tx_hash,
                         multisig_tx.safe_tx_hash.hex())
        self.assertEqual(MultisigConfirmation.objects.count(), 4)

        # Enable module (nonce: 3) ---------------------------------------------------------------------
        module_address = Account.create().address
        data = HexBytes(
            self.safe_contract_V1_3_0.functions.enableModule(
                module_address
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, EnabledModule, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one enabling the module
        self.assertEqual(SafeStatus.objects.count(), 10)
        safe_status = SafeStatus.objects.last_for_address(safe_address)  # Processed execTransaction and enableModule
        self.assertEqual(safe_status.enabled_modules, [module_address])
        self.assertEqual(safe_status.nonce, 4)

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[1]  # Just processed execTransaction
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.nonce, 4)

        self.assertEqual(MultisigTransaction.objects.count(), 4)
        self.assertEqual(MultisigTransaction.objects.order_by('-nonce')[0].safe_tx_hash,
                         multisig_tx.safe_tx_hash.hex())
        self.assertEqual(MultisigConfirmation.objects.count(), 5)

        # Check SafeReceived (ether received) on Safe -----------------------------------------------------------------
        value = 1256
        self.ethereum_client.get_transaction_receipt(self.send_ether(safe_address, value))
        # Process events: SafeReceived
        self.assertEqual(self.safe_events_indexer.start(), 1)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Check there's an ether transaction
        internal_tx_queryset = InternalTx.objects.filter(
            value=value,
            tx_type=InternalTxType.CALL.value,
            call_type=EthereumTxCallType.CALL.value
        )
        self.assertTrue(internal_tx_queryset.exists())
        self.assertTrue(internal_tx_queryset.get().is_ether_transfer)

        # Set fallback handler (nonce: 4) --------------------------------------------------------------------------
        new_fallback_handler = Account.create().address
        data = HexBytes(
            self.safe_contract_V1_3_0.functions.setFallbackHandler(
                new_fallback_handler
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ChangedFallbackHandler, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one changing the fallback handler
        self.assertEqual(SafeStatus.objects.count(), 12)
        safe_status = SafeStatus.objects.last_for_address(safe_address)  # Processed execTransaction and setFallbackHandler
        self.assertEqual(safe_status.fallback_handler, new_fallback_handler)
        self.assertEqual(safe_status.enabled_modules, [module_address])
        self.assertEqual(safe_status.nonce, 5)

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[1]  # Just processed execTransaction
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.enabled_modules, [module_address])
        self.assertEqual(safe_status.nonce, 5)

        self.assertEqual(MultisigTransaction.objects.count(), 5)
        self.assertEqual(MultisigTransaction.objects.order_by('-nonce')[0].safe_tx_hash,
                         multisig_tx.safe_tx_hash.hex())
        self.assertEqual(MultisigConfirmation.objects.count(), 6)

        # Disable Module (nonce: 5) ----------------------------------------------------------------------------------
        data = HexBytes(
            self.safe_contract_V1_3_0.functions.disableModule(
                SENTINEL_ADDRESS,
                module_address
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, DisabledModule, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one disabling the module
        self.assertEqual(SafeStatus.objects.count(), 14)
        safe_status = SafeStatus.objects.last_for_address(safe_address)  # Processed execTransaction and disableModule
        self.assertEqual(safe_status.nonce, 6)
        self.assertEqual(safe_status.enabled_modules, [])

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[1]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 6)
        self.assertEqual(safe_status.enabled_modules, [module_address])

        self.assertEqual(MultisigTransaction.objects.count(), 6)
        self.assertEqual(MultisigTransaction.objects.order_by('-nonce')[0].safe_tx_hash,
                         multisig_tx.safe_tx_hash.hex())
        self.assertEqual(MultisigConfirmation.objects.count(), 7)

        # ApproveHash (no nonce) ------------------------------------------------------------------------------------
        random_hash = self.w3.sha3(text='Get schwifty')
        tx = safe.get_contract().functions.approveHash(
            random_hash
        ).buildTransaction({'from': owner_account_1.address,
                            'nonce': self.ethereum_client.get_nonce_for_account(owner_account_1.address)})
        tx = owner_account_1.signTransaction(tx)
        self.w3.eth.sendRawTransaction(tx['rawTransaction'])
        # Process events: ApproveHash
        self.assertEqual(self.safe_events_indexer.start(), 1)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # No SafeStatus was added
        self.assertEqual(SafeStatus.objects.count(), 14)
        # Check a MultisigConfirmation was created
        self.assertTrue(MultisigConfirmation.objects.filter(multisig_transaction_hash=random_hash.hex()).exists())
        self.assertEqual(MultisigTransaction.objects.count(), 6)  # No MultisigTransaction was created
        self.assertEqual(MultisigConfirmation.objects.count(), 8)  # A MultisigConfirmation was created

        # Set guard (nonce: 6) INVALIDATES SAFE, as no more transactions can be done ---------------------------------
        guard_address = Account.create().address
        data = HexBytes(
            self.safe_contract_V1_3_0.functions.setGuard(
                guard_address
            ).buildTransaction({'gas': 1, 'gasPrice': 1})['data']
        )

        multisig_tx = safe.build_multisig_tx(safe_address, 0, data)
        multisig_tx.sign(owner_account_1.key)
        multisig_tx.sign(owner_account_2.key)  # Use 2 signatures to test multiple confirmations parsing
        multisig_tx.execute(self.ethereum_test_account.key)
        # Process events: SafeMultiSigTransaction, ChangedGuard, ExecutionSuccess
        self.assertEqual(self.safe_events_indexer.start(), 3)
        self.safe_tx_processor.process_decoded_transactions(txs_decoded_queryset.all())
        # Add one SafeStatus increasing the nonce and another one changing the guard
        self.assertEqual(SafeStatus.objects.count(), 16)
        safe_status = SafeStatus.objects.last_for_address(safe_address)  # Processed execTransaction and setGuard
        self.assertEqual(safe_status.nonce, 7)
        self.assertEqual(safe_status.guard, guard_address)

        safe_status = SafeStatus.objects.sorted_by_internal_tx()[1]  # Just processed execTransaction
        self.assertEqual(safe_status.nonce, 7)
        self.assertIsNone(safe_status.guard)

        # Check master copy did not change during the execution
        self.assertEqual(SafeStatus.objects.last_for_address(safe_address).master_copy,
                         self.safe_contract_V1_3_0.address)

        self.assertEqual(MultisigTransaction.objects.count(), 7)
        self.assertEqual(MultisigTransaction.objects.order_by('-nonce')[0].safe_tx_hash,
                         multisig_tx.safe_tx_hash.hex())
        self.assertEqual(MultisigConfirmation.objects.count(), 10)
