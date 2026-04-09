# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from unittest import mock

from django.test import TestCase

from eth_account import Account
from eth_utils import keccak
from safe_eth.eth.ethereum_client import TracingManager
from safe_eth.eth.utils import fast_keccak_text
from safe_eth.safe.safe_signature import SafeSignatureType
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.safe_messages.models import SafeMessageConfirmation
from safe_transaction_service.safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)

from ..indexers.tx_processor import (
    CannotFindPreviousTrace,
    ModuleCannotBeDisabled,
    SafeTxProcessor,
    SafeTxProcessorProvider,
)
from ..models import (
    InternalTxDecoded,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
    SafeLastStatus,
    SafeRelevantTransaction,
    SafeStatus,
)
from .factories import (
    EthereumTxFactory,
    InternalTxDecodedFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractDelegateFactory,
    SafeLastStatusFactory,
    SafeMasterCopyFactory,
)
from .mocks.traces import call_trace, module_traces, testnet_traces

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
        self.assertEqual(SafeRelevantTransaction.objects.count(), 0)
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="setup",
                    owner=owner,
                    threshold=threshold,
                    fallback_handler=fallback_handler,
                    internal_tx__to=master_copy,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                )
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 0)
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
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
                InternalTxDecodedFactory(
                    function_name="addOwnerWithThreshold",
                    owner=new_owner,
                    threshold=threshold,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 1)

        self.assertEqual(SafeStatus.objects.count(), 3)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.owners, [new_owner, owner])
        self.assertEqual(safe_status.nonce, 1)
        self.assertEqual(safe_status.threshold, threshold)

        safe_contract_delegate = SafeContractDelegateFactory(
            delegator=owner, safe_contract_id=safe_address
        )
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                safe_address, [owner]
            ),
            {safe_contract_delegate.delegate},
        )

        another_owner = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
                InternalTxDecodedFactory(
                    function_name="swapOwner",
                    old_owner=owner,
                    owner=another_owner,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 2)
        self.assertEqual(SafeStatus.objects.count(), 5)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.owners, [new_owner, another_owner])
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                safe_address, [owner]
            ),
            set(),
        )
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
        # This won't be deleted: message belongs to a different Safe, deletion is scoped to safe_address
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        unused_message_confirmation = SafeMessageConfirmationFactory(
            owner=another_owner, safe_message=safe_message
        )
        # This won't be deleted either
        unused_message_confirmation_2 = SafeMessageConfirmationFactory(
            safe_message=unused_message_confirmation.safe_message
        )
        self.assertEqual(SafeMessageConfirmation.objects.count(), 2)
        number_confirmations = MultisigConfirmation.objects.count()
        safe_contract_delegate_another_owner = SafeContractDelegateFactory(
            delegator=another_owner, safe_contract_id=safe_address
        )
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                safe_address, [another_owner]
            ),
            {safe_contract_delegate_another_owner.delegate},
        )
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
                InternalTxDecodedFactory(
                    function_name="removeOwner",
                    old_owner=another_owner,
                    threshold=threshold,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 3)
        # At least 1 confirmation is always added by `execTransaction` and 1 should be removed
        self.assertEqual(
            MultisigConfirmation.objects.count(), number_confirmations + 1 - 1
        )
        unused_multisig_confirmation.multisig_transaction.delete()  # Remove this transaction inserted manually
        # Both confirmations remain: deletion is scoped to safe_address, but this message belongs to a different Safe
        self.assertEqual(SafeMessageConfirmation.objects.count(), 2)
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
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                safe_address, [another_owner]
            ),
            set(),
        )
        self.assertEqual(safe_status.nonce, 3)
        self.assertEqual(safe_status.threshold, threshold)

        fallback_handler = Account.create().address
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
                InternalTxDecodedFactory(
                    function_name="setFallbackHandler",
                    fallback_handler=fallback_handler,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 4)
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
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
                InternalTxDecodedFactory(
                    function_name="changeMasterCopy",
                    master_copy=master_copy,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 5)
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
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
                InternalTxDecodedFactory(
                    function_name="enableModule",
                    module=module,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 6)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.enabled_modules, [module])
        self.assertEqual(safe_status.nonce, 6)

        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="execTransaction",
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
                InternalTxDecodedFactory(
                    function_name="disableModule",
                    module=module,
                    internal_tx___from=safe_address,
                    internal_tx__value=0,
                ),
            ]
        )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 7)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.enabled_modules, [])
        self.assertEqual(safe_status.nonce, 7)

        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=testnet_traces,
        ):
            # call_trace has [] as a trace address and module txs need to get the grandfather tx, so [0,0] must
            # be used
            tx_processor.process_decoded_transactions(
                [
                    InternalTxDecodedFactory(
                        function_name="execTransactionFromModule",
                        internal_tx___from=safe_address,
                        internal_tx__trace_address="0,0",
                        internal_tx__value=0,
                    )
                ]
            )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 8)
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
        hash_to_approve = to_0x_hex_str(keccak(text="HariSeldon"))
        owner_approving = Account.create().address
        approve_hash_decoded_tx = InternalTxDecodedFactory(
            function_name="approveHash",
            hash_to_approve=hash_to_approve,
            internal_tx___from=safe_address,
            internal_tx__trace_address="0,1,0",
            internal_tx__value=0,
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
                        function_name="execTransaction",
                        internal_tx___from=safe_address,
                        internal_tx__value=0,
                    ),
                    approve_hash_decoded_tx,
                ]
            )
        self.assertEqual(SafeRelevantTransaction.objects.count(), 9)
        safe_status = SafeStatus.objects.last_for_address(safe_address)
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_status, SafeStatus.from_status_instance(safe_last_status))
        self.assertEqual(safe_status.nonce, 8)
        multisig_confirmation = MultisigConfirmation.objects.get(
            multisig_transaction_hash=hash_to_approve
        )
        self.assertEqual(
            multisig_confirmation.signature_type,
            SafeSignatureType.APPROVED_HASH.value,
        )

    def test_tx_processor_get_execution_result(self):
        tx_processor = self.tx_processor
        other_hash = to_0x_hex_str(fast_keccak_text("hola"))

        # ExecutionFailure v1.4.1 — indexed txHash in topics[1], payment=0 in data
        logs = [
            {
                "topics": [
                    "0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23",
                    "0xd6dfcc85421ca06ca8501b3f3e843b6db54a291d4545377a0db34f79cb02e58c",
                ],
                "data": "0x0000000000000000000000000000000000000000000000000000000000000000",
            }
        ]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertEqual(
            tx_processor.get_execution_result(
                ethereum_tx,
                "0xd6dfcc85421ca06ca8501b3f3e843b6db54a291d4545377a0db34f79cb02e58c",
            ),
            (True, 0),
        )
        self.assertEqual(
            tx_processor.get_execution_result(ethereum_tx, other_hash), (False, None)
        )

        # ExecutionFailure v1.3.0 — unindexed txHash, payment in data
        logs = [
            {
                "topics": [
                    "0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23",
                ],
                "data": "0xb3418ba0a5d1af8a5e17b410e54f709e89ed6f45362ef772c12f70529c538ae7"
                "0000000000000000000000000000000000000000000000000000023f62a7b29c",
            }
        ]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertEqual(
            tx_processor.get_execution_result(
                ethereum_tx,
                "0xb3418ba0a5d1af8a5e17b410e54f709e89ed6f45362ef772c12f70529c538ae7",
            ),
            (True, 2471261352604),
        )
        self.assertEqual(
            tx_processor.get_execution_result(ethereum_tx, other_hash), (False, None)
        )

        # ExecutionSuccess v1.3.0 — unindexed txHash, payment=0 in data
        logs = [
            {
                "topics": [
                    "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e",
                ],
                "data": "0x71a7bab18403a05d3ab369b3206ceaca9b4ab3e29d0b804ed7d05c6403a53df8"
                "0000000000000000000000000000000000000000000000000000000000000000",
            }
        ]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertEqual(
            tx_processor.get_execution_result(
                ethereum_tx,
                "0x71a7bab18403a05d3ab369b3206ceaca9b4ab3e29d0b804ed7d05c6403a53df8",
            ),
            (False, 0),
        )
        self.assertEqual(
            tx_processor.get_execution_result(ethereum_tx, other_hash), (False, None)
        )

        # ExecutionSuccess v1.4.1 — indexed txHash in topics[1], payment in data
        logs = [
            {
                "topics": [
                    "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e",
                    "0xa3324f8210e3d1772329133a15ad3bb31b848c8ca2498e36a787982a685d2484",
                ],
                "data": "0x0000000000000000000000000000000000000000000000000000038fc9cbcc74",
            }
        ]
        ethereum_tx = EthereumTxFactory(logs=logs)
        self.assertEqual(
            tx_processor.get_execution_result(
                ethereum_tx,
                "0xa3324f8210e3d1772329133a15ad3bb31b848c8ca2498e36a787982a685d2484",
            ),
            (False, 3916100783220),
        )
        self.assertEqual(
            tx_processor.get_execution_result(ethereum_tx, other_hash), (False, None)
        )

        # No matching log → default
        ethereum_tx = EthereumTxFactory(logs=[])
        self.assertEqual(
            tx_processor.get_execution_result(
                ethereum_tx,
                "0xa3324f8210e3d1772329133a15ad3bb31b848c8ca2498e36a787982a685d2484",
            ),
            (False, None),
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
        tx_processor.process_decoded_transactions(
            [
                InternalTxDecodedFactory(
                    function_name="setup",
                    owner=owner,
                    threshold=threshold,
                    fallback_handler=fallback_handler,
                    internal_tx__to=safe_1_1_0_master_copy.address,
                    internal_tx___from=safe_address,
                )
            ]
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
        with self.assertRaises(
            CannotFindPreviousTrace
        ):  # trace_transaction not supported
            safe_tx_processor.process_decoded_transactions(
                [module_internal_tx_decoded]
            )[0]
            self.assertEqual(ModuleTransaction.objects.count(), 0)

        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=module_traces,
        ):
            safe_tx_processor.process_decoded_transactions(
                [module_internal_tx_decoded]
            )[0]
            self.assertEqual(ModuleTransaction.objects.count(), 1)
            module_tx = ModuleTransaction.objects.get()
            self.assertEqual(
                to_0x_hex_str(bytes(module_tx.data)),
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

    def test_process_disable_module_tx(self):
        safe_tx_processor = self.tx_processor
        safe_last_status = SafeLastStatusFactory(nonce=0)
        safe_address = safe_last_status.address
        module = Account.create().address
        disable_module_tx_decoded = InternalTxDecodedFactory(
            function_name="disableModule",
            module=module,
            internal_tx___from=safe_address,
            internal_tx__value=0,
        )

        with self.assertLogs(
            "safe_transaction_service.history.indexers.tx_processor", level="ERROR"
        ) as cm:
            self.assertFalse(
                safe_tx_processor.process_decoded_transactions(
                    [disable_module_tx_decoded]
                )[0]
            )
            self.assertTrue(
                any(ModuleCannotBeDisabled.__name__ in line for line in cm.output)
            )

        enable_module_tx_decoded = InternalTxDecodedFactory(
            function_name="enableModule",
            module=module,
            internal_tx___from=safe_address,
            internal_tx__value=0,
        )
        self.assertTrue(
            safe_tx_processor.process_decoded_transactions([enable_module_tx_decoded])[
                0
            ]
        )
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_last_status.enabled_modules, [module])
        self.assertTrue(
            safe_tx_processor.process_decoded_transactions([disable_module_tx_decoded])[
                0
            ]
        )
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_last_status.enabled_modules, [])

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
            safe_last_status, safe_last_status.internal_tx, ["nonce"]
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
            new_safe_last_status, new_safe_last_status.internal_tx, []
        )
        safe_last_status_db = SafeLastStatus.objects.get()
        self.assertEqual(safe_last_status_db.address, safe_address)
        self.assertEqual(safe_last_status_db.nonce, 1)
