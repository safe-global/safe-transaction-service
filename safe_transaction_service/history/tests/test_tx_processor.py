import logging
from unittest import mock

from django.test import TestCase

from eth_account import Account
from eth_utils import keccak
from web3 import Web3

from gnosis.eth.ethereum_client import TracingManager
from gnosis.safe.safe_signature import SafeSignatureType
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.safe_messages.models import SafeMessageConfirmation
from safe_transaction_service.safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)

from ..indexers.tx_processor import SafeTxProcessor, SafeTxProcessorProvider
from ..models import (
    InternalTxDecoded,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeLastStatus,
    SafeStatus,
)
from .factories import (
    EthereumTxFactory,
    InternalTxDecodedFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeLastStatusFactory,
    SafeMasterCopyFactory,
)
from .mocks.traces import call_trace, module_traces, rinkeby_traces

logger = logging.getLogger(__name__)


class TestSafeTxProcessor(SafeTestCaseMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tx_processor: SafeTxProcessor = SafeTxProcessorProvider()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        SafeTxProcessorProvider.del_singleton()

    def test_tx_processor_with_factory(self):
        tx_processor = self.tx_processor
        owner = Account.create().address
        safe_address = Account.create().address
        fallback_handler = Account.create().address
        master_copy = Account.create().address
        threshold = 1
        tx_processor.process_decoded_transaction(
            InternalTxDecodedFactory(
                function_name="setup",
                owner=owner,
                threshold=threshold,
                fallback_handler=fallback_handler,
                internal_tx__to=master_copy,
                internal_tx___from=safe_address,
            )
        )
        self.assertTrue(SafeContract.objects.get(address=safe_address))
        safe_status = SafeStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.master_copy, master_copy)
        self.assertEqual(safe_status.owners, [owner])
        self.assertEqual(safe_status.threshold, threshold)

        # execTransaction should be calling addOwnerWithThreshold, so we process it together
        threshold = 2
        new_owner = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="addOwnerWithThreshold",
                    owner=new_owner,
                    threshold=threshold,
                    internal_tx___from=safe_address,
                ),
            ]
        )

        self.assertEqual(SafeStatus.objects.count(), 3)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.owners, [new_owner, owner])
        self.assertEqual(safe_status.nonce, 1)
        self.assertEqual(safe_status.threshold, threshold)

        another_owner = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="swapOwner",
                    old_owner=owner,
                    owner=another_owner,
                    internal_tx___from=safe_address,
                ),
            ]
        )
        self.assertEqual(SafeStatus.objects.count(), 5)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.owners, [new_owner, another_owner])
        self.assertEqual(safe_status.nonce, 2)
        self.assertEqual(safe_status.threshold, threshold)

        threshold = 1
        # Check deleting the owner did delete this pending confirmation for both signature and transaction
        # It will insert a transaction we will remove after we check the confirmation was deleted
        unused_multisig_confirmation = MultisigConfirmationFactory(
            owner=another_owner,
            multisig_transaction__ethereum_tx=None,
            multisig_transaction__nonce=safe_status.nonce + 1,
            multisig_transaction__safe=safe_address,
        )
        # This will be deleted
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        unused_message_confirmation = SafeMessageConfirmationFactory(
            owner=another_owner, safe_message=safe_message
        )
        # This won't be deleted
        unused_message_confirmation_2 = SafeMessageConfirmationFactory(
            safe_message=unused_message_confirmation.safe_message
        )
        self.assertEqual(SafeMessageConfirmation.objects.count(), 2)
        number_confirmations = MultisigConfirmation.objects.count()
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="removeOwner",
                    old_owner=another_owner,
                    threshold=threshold,
                    internal_tx___from=safe_address,
                ),
            ]
        )
        # At least 1 confirmation is always added by `execTransaction` and 1 should be removed
        self.assertEqual(
            MultisigConfirmation.objects.count(), number_confirmations + 1 - 1
        )
        unused_multisig_confirmation.multisig_transaction.delete()  # Remove this transaction inserted manually
        self.assertEqual(SafeMessageConfirmation.objects.count(), 1)
        self.assertTrue(
            SafeMessageConfirmation.objects.filter(
                owner=unused_message_confirmation_2.owner
            ).exists()
        )
        self.assertEqual(SafeStatus.objects.count(), 7)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.owners, [new_owner])
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, threshold)

        fallback_handler = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="setFallbackHandler",
                    fallback_handler=fallback_handler,
                    internal_tx___from=safe_address,
                ),
            ]
        )
        self.assertEqual(SafeStatus.objects.count(), 9)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.fallback_handler, fallback_handler)
        self.assertEqual(safe_status.nonce, 4)

        master_copy = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="changeMasterCopy",
                    master_copy=master_copy,
                    internal_tx___from=safe_address,
                ),
            ]
        )
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.master_copy, master_copy)
        self.assertEqual(safe_status.nonce, 5)
        self.assertEqual(safe_status.enabled_modules, [])

        module = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="enableModule",
                    module=module,
                    internal_tx___from=safe_address,
                ),
            ]
        )
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.enabled_modules, [module])
        self.assertEqual(safe_status.nonce, 6)

        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="disableModule",
                    module=module,
                    internal_tx___from=safe_address,
                ),
            ]
        )
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.nonce, 7)

        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=rinkeby_traces,
        ):
            # call_trace has [] as a trace address and module txs need to get the grandfather tx, so [0,0] must
            # be used
            module_internal_tx_decoded = InternalTxDecodedFactory(
                function_name="execTransactionFromModule",
                internal_tx___from=safe_address,
                internal_tx__trace_address="0,0",
            )
            tx_processor.process_decoded_transactions(
                [
                    module_internal_tx_decoded,
                ]
            )
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.nonce, 7)  # Nonce not incrementing
        self.assertEqual(ModuleTransaction.objects.count(), 1)

        self.assertEqual(MultisigTransaction.objects.count(), 7)
        self.assertEqual(
            MultisigTransaction.objects.count(),
            InternalTxDecoded.objects.filter(function_name="execTransaction").count(),
        )
        for multisig_transaction in MultisigTransaction.objects.all():
            self.assertTrue(multisig_transaction.trusted)

        # Test ApproveHash. For that we need the `previous_trace` to get the owner
        hash_to_approve = keccak(text="HariSeldon").hex()
        owner_approving = Account.create().address
        approve_hash_decoded_tx = InternalTxDecodedFactory(
            function_name="approveHash",
            hash_to_approve=hash_to_approve,
            internal_tx___from=safe_address,
            internal_tx__trace_address="0,1,0",
        )
        approve_hash_previous_call_trace = dict(call_trace)
        approve_hash_previous_call_trace["action"]["from"] = owner_approving
        approve_hash_previous_call_trace["traceAddress"] = [0, 1]
        # Not needed
        # approve_hash_call_trace['transactionHash'] = approve_hash_decoded_tx.internal_tx.ethereum_tx_id
        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=[approve_hash_previous_call_trace],
        ):
            tx_processor.process_decoded_transactions(
                [
                    InternalTxDecodedFactory(
                        function_name="execTransaction", internal_tx___from=safe_address
                    ),
                    approve_hash_decoded_tx,
                ]
            )
            safe_status = SafeStatus.objects.last_for_address(safe_address)
            safe_last_status = SafeLastStatus.objects.get(address=safe_address)
            self.assertEqual(
                safe_status, SafeStatus.from_status_instance(safe_last_status)
            )
            self.assertEqual(safe_status.nonce, 8)
            multisig_confirmation = MultisigConfirmation.objects.get(
                multisig_transaction_hash=hash_to_approve
            )
            self.assertEqual(
                multisig_confirmation.signature_type,
                SafeSignatureType.APPROVED_HASH.value,
            )

    def test_tx_processor_is_failed(self):
        tx_processor = self.tx_processor
        # Event for Safes < 1.1.1
        logs = [
            {
                "data": "0x0034bff0dedc4c75f43df64a179ff26d56b99fa742fcfaeeee51e2da4e279b67",
                "topics": [
                    "0xabfd711ecdd15ae3a6b3ad16ff2e9d81aec026a39d16725ee164be4fbf857a7c"
                ],
            }
        ]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertTrue(tx_processor.is_failed(ethereum_tx, logs[0]["data"]))
        self.assertFalse(
            tx_processor.is_failed(ethereum_tx, Web3.keccak(text="hola").hex())
        )

        # Event for Safes >= 1.1.1
        safe_tx_hash = (
            "0x4c15b21b9c3b57aebba3c274bf0a437950bd0eea46bc7a7b2df892f91f720311"
        )
        logs = [
            {
                "data": "0x4c15b21b9c3b57aebba3c274bf0a437950bd0eea46bc7a7b2df892f91f720311"
                "0000000000000000000000000000000000000000000000000000000000000000",
                "topics": [
                    "0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23"
                ],
            }
        ]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertTrue(tx_processor.is_failed(ethereum_tx, safe_tx_hash))
        self.assertFalse(
            tx_processor.is_failed(ethereum_tx, Web3.keccak(text="hola").hex())
        )

        # Event for Safes >= 1.4.1
        safe_tx_hash = (
            "0x4c15b21b9c3b57aebba3c274bf0a437950bd0eea46bc7a7b2df892f91f720311"
        )
        logs = [
            {
                "data": "0000000000000000000000000000000000000000000000000000000000000000",
                "topics": [
                    "0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23",
                    "0x4c15b21b9c3b57aebba3c274bf0a437950bd0eea46bc7a7b2df892f91f720311",
                ],
            }
        ]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertTrue(tx_processor.is_failed(ethereum_tx, safe_tx_hash))
        self.assertFalse(
            tx_processor.is_failed(ethereum_tx, Web3.keccak(text="hola").hex())
        )

    def test_tx_is_version_breaking_signatures(self):
        tx_processor = self.tx_processor
        self.assertTrue(tx_processor.is_version_breaking_signatures("0.0.1", "1.1.1"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("0.0.1", "1.3.0"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("0.0.1", "1.4.0"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.0.0", "1.3.0"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.1.1", "1.3.0"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.2.0", "1.3.0"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.2.1", "1.4.0"))
        self.assertFalse(tx_processor.is_version_breaking_signatures("1.0.0", "1.2.2"))
        self.assertFalse(tx_processor.is_version_breaking_signatures("1.1.0", "1.2.0"))
        self.assertFalse(tx_processor.is_version_breaking_signatures("0.0.1", "0.9.0"))

        # Reversed
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.1.1", "0.0.1"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.3.0", "0.0.1"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.3.0", "0.0.1"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.3.0", "1.0.0"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.3.0", "1.1.1"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.3.0", "1.2.0"))
        self.assertTrue(tx_processor.is_version_breaking_signatures("1.4.0", "1.2.1"))
        self.assertFalse(tx_processor.is_version_breaking_signatures("1.2.2", "1.0.0"))
        self.assertFalse(tx_processor.is_version_breaking_signatures("1.2.0", "1.1.0"))
        self.assertFalse(tx_processor.is_version_breaking_signatures("0.9.0", "0.0.1"))

    def test_tx_processor_change_master_copy(self):
        tx_processor = self.tx_processor
        owner = Account.create().address
        safe_address = Account.create().address
        fallback_handler = Account.create().address
        threshold = 1
        safe_1_1_0_master_copy = SafeMasterCopyFactory(version="1.1.0")
        safe_1_2_0_master_copy = SafeMasterCopyFactory(version="1.2.0")
        safe_1_3_0_master_copy = SafeMasterCopyFactory(version="1.3.0")
        tx_processor.process_decoded_transaction(
            InternalTxDecodedFactory(
                function_name="setup",
                owner=owner,
                threshold=threshold,
                fallback_handler=fallback_handler,
                internal_tx__to=safe_1_1_0_master_copy.address,
                internal_tx___from=safe_address,
            )
        )
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="changeMasterCopy",
                    master_copy=safe_1_2_0_master_copy.address,
                    internal_tx___from=safe_address,
                ),
            ]
        )
        self.assertEqual(MultisigTransaction.objects.get().nonce, 0)
        MultisigTransactionFactory(
            safe=safe_address, nonce=1, ethereum_tx=None
        )  # This will not be deleted as execTransaction will insert a tx with nonce=1
        MultisigTransactionFactory(
            safe=safe_address, nonce=2, ethereum_tx=None
        )  # This will be deleted when migrating to the 1.3.0 master copy
        self.assertEqual(
            MultisigTransaction.objects.filter(safe=safe_address, nonce=2).count(), 1
        )
        self.assertEqual(MultisigTransaction.objects.count(), 3)
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction", internal_tx___from=safe_address
                ),
                InternalTxDecodedFactory(
                    function_name="changeMasterCopy",
                    master_copy=safe_1_3_0_master_copy.address,
                    internal_tx___from=safe_address,
                ),
            ]
        )

        self.assertEqual(
            MultisigTransaction.objects.filter(safe=safe_address, nonce=1).count(), 2
        )
        self.assertEqual(
            MultisigTransaction.objects.filter(safe=safe_address, nonce=2).count(), 0
        )  # It was deleted
        self.assertEqual(MultisigTransaction.objects.count(), 3)

    def test_process_module_tx(self):
        safe_tx_processor = self.tx_processor
        safe_last_status = SafeLastStatusFactory()
        module_internal_tx_decoded = InternalTxDecodedFactory(
            function_name="execTransactionFromModule",
            internal_tx___from=safe_last_status.address,
            internal_tx__to="0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
            internal_tx__trace_address="0,0,0,4",
            internal_tx__ethereum_tx__tx_hash="0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        )

        self.assertEqual(ModuleTransaction.objects.count(), 0)
        with self.assertRaises(ValueError):  # trace_transaction not supported
            safe_tx_processor.process_decoded_transaction(module_internal_tx_decoded)
            self.assertEqual(ModuleTransaction.objects.count(), 0)

        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=module_traces,
        ):
            safe_tx_processor.process_decoded_transaction(module_internal_tx_decoded)
            self.assertEqual(ModuleTransaction.objects.count(), 1)
            module_tx = ModuleTransaction.objects.get()
            self.assertEqual(
                "0x" + bytes(module_tx.data).hex(),
                module_internal_tx_decoded.arguments["data"],
            )
            self.assertEqual(
                module_tx.module, "0x03967E5b71577ba3498E1a87E425139B22B3c085"
            )
            self.assertEqual(
                module_tx.operation, module_internal_tx_decoded.arguments["operation"]
            )
            self.assertEqual(module_tx.to, module_internal_tx_decoded.arguments["to"])
            self.assertEqual(
                module_tx.value, module_internal_tx_decoded.arguments["value"]
            )

    def test_store_new_safe_status(self):
        # Create a new SafeLastStatus
        safe_last_status = SafeLastStatusFactory(nonce=0)
        safe_address = safe_last_status.address
        safe_last_status_db = SafeLastStatus.objects.get()
        self.assertEqual(safe_last_status_db.address, safe_address)
        self.assertEqual(safe_last_status_db.nonce, 0)

        # Increase nonce and store it
        safe_last_status.nonce = 5
        self.tx_processor.store_new_safe_status(
            safe_last_status, safe_last_status.internal_tx
        )
        safe_last_status_db = SafeLastStatus.objects.get()
        self.assertEqual(safe_last_status_db.address, safe_address)
        self.assertEqual(safe_last_status_db.nonce, 5)

        # Use the factory to create a new SafeLastStatus
        new_safe_last_status = SafeLastStatusFactory(nonce=1)
        # Remove it, as we want to use it to replace our previous SafeLastStatus
        new_safe_last_status.delete()
        self.assertNotEqual(new_safe_last_status.address, safe_address)
        new_safe_last_status.address = safe_address

        self.tx_processor.store_new_safe_status(
            new_safe_last_status, new_safe_last_status.internal_tx
        )
        safe_last_status_db = SafeLastStatus.objects.get()
        self.assertEqual(safe_last_status_db.address, safe_address)
        self.assertEqual(safe_last_status_db.nonce, 1)
