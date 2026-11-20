import copy
import itertools
import logging
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account
from eth_utils import keccak
from hexbytes import HexBytes
from safe_eth.eth.ethereum_client import TracingManager
from safe_eth.eth.utils import fast_keccak_text, fast_to_checksum_address
from safe_eth.safe import SafeTx
from safe_eth.safe.safe_signature import SafeSignatureType
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.events.services.queue_service import QueueService
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
    TransactionServiceEventType,
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
from .utils import get_sent_event_types

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
        tx_processor.process_decoded_transaction(
            InternalTxDecodedFactory(
                function_name="setup",
                owner=owner,
                threshold=threshold,
                fallback_handler=fallback_handler,
                internal_tx__to=master_copy,
                internal_tx___from=safe_address,
                internal_tx__value=0,
            )
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
        self.assertEqual(multisig_confirmation.safe_address, safe_address)

    def _process_approve_hash(
        self,
        safe_address: str,
        owner: str,
        hash_to_approve: str,
        is_indexed_from_traces: bool,
    ) -> None:
        """
        Process an ``approveHash`` called by ``owner`` on ``safe_address``, built like
        the L1 trace indexer (owner taken from the previous trace) or like the L2
        event indexer (owner in the event arguments)
        """
        if is_indexed_from_traces:
            approve_hash_decoded_tx = InternalTxDecodedFactory(
                function_name="approveHash",
                hash_to_approve=hash_to_approve,
                internal_tx___from=safe_address,
                internal_tx__trace_address="0,1,0",
                internal_tx__value=0,
            )
            previous_call_trace = copy.deepcopy(call_trace)
            previous_call_trace["action"]["from"] = owner
            previous_call_trace["traceAddress"] = [0, 1]
            with mock.patch.object(
                TracingManager,
                "trace_transaction",
                autospec=True,
                return_value=[previous_call_trace],
            ):
                self.tx_processor.process_decoded_transactions(
                    [approve_hash_decoded_tx]
                )
        else:
            self.tx_processor.process_decoded_transactions(
                [
                    InternalTxDecodedFactory(
                        function_name="approveHash",
                        arguments={"hashToApprove": hash_to_approve, "owner": owner},
                        internal_tx___from=safe_address,
                        internal_tx__value=0,
                    )
                ]
            )

    def _propose_and_approve_hash(
        self,
        tx_safe_address: str,
        approving_safe_address: str,
        owner: str,
        is_indexed_from_traces: bool,
        is_proposed_first: bool,
    ) -> MultisigTransaction:
        """
        Store an untrusted proposal for ``tx_safe_address`` and process an
        ``approveHash`` of its hash by ``owner`` on ``approving_safe_address``,
        in the given order

        :return: The proposal, read again from the database
        """
        safe_tx_hash = to_0x_hex_str(fast_keccak_text(approving_safe_address + owner))

        def propose():
            MultisigTransactionFactory(
                safe_tx_hash=safe_tx_hash,
                safe=tx_safe_address,
                trusted=False,
                ethereum_tx=None,
            )

        def approve_hash():
            self._process_approve_hash(
                approving_safe_address, owner, safe_tx_hash, is_indexed_from_traces
            )

        steps = (
            [propose, approve_hash] if is_proposed_first else [approve_hash, propose]
        )
        with self.captureOnCommitCallbacks(execute=True):
            for step in steps:
                step()
        return MultisigTransaction.objects.get(safe_tx_hash=safe_tx_hash)

    @mock.patch.object(QueueService, "send_event")
    def test_approve_hash_on_another_safe_does_not_trust_transaction(
        self, send_event_mock: MagicMock
    ):
        """
        ``approveHash`` called on Safe A with the hash of an untrusted proposal for
        Safe B is not bound to the proposal, whatever arrives first and even if the
        approving owner is an owner of B. The proposal stays untrusted and no
        PENDING_MULTISIG_TRANSACTION is sent
        """
        for is_indexed_from_traces, is_proposed_first in itertools.product(
            (True, False), repeat=2
        ):
            with self.subTest(
                is_indexed_from_traces=is_indexed_from_traces,
                is_proposed_first=is_proposed_first,
            ):
                send_event_mock.reset_mock()
                # An L2 event can carry any owner, so use an owner of the victim Safe
                victim_owner = Account.create().address
                victim_safe_status = SafeLastStatusFactory(owners=[victim_owner])
                attacker_safe_status = SafeLastStatusFactory(owners=[victim_owner])

                multisig_tx = self._propose_and_approve_hash(
                    victim_safe_status.address,
                    attacker_safe_status.address,
                    victim_owner,
                    is_indexed_from_traces,
                    is_proposed_first,
                )

                self.assertFalse(multisig_tx.trusted)
                self.assertFalse(multisig_tx.confirmations.exists())
                attacker_confirmation = MultisigConfirmation.objects.get(
                    multisig_transaction_hash=multisig_tx.safe_tx_hash
                )
                self.assertIsNone(attacker_confirmation.multisig_transaction_id)
                self.assertEqual(
                    attacker_confirmation.safe_address, attacker_safe_status.address
                )
                sent_event_types = get_sent_event_types(send_event_mock)
                self.assertNotIn(
                    TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name,
                    sent_event_types,
                )

    @mock.patch.object(QueueService, "send_event")
    def test_approve_hash_on_transaction_safe_trusts_transaction(
        self, send_event_mock: MagicMock
    ):
        """
        ``approveHash`` called on Safe B with the hash of an untrusted proposal for B
        is bound to the proposal, which becomes trusted and is published, whatever
        arrives first
        """
        for is_indexed_from_traces, is_proposed_first in itertools.product(
            (True, False), repeat=2
        ):
            with self.subTest(
                is_indexed_from_traces=is_indexed_from_traces,
                is_proposed_first=is_proposed_first,
            ):
                send_event_mock.reset_mock()
                owner = Account.create().address
                safe_status = SafeLastStatusFactory(owners=[owner])

                multisig_tx = self._propose_and_approve_hash(
                    safe_status.address,
                    safe_status.address,
                    owner,
                    is_indexed_from_traces,
                    is_proposed_first,
                )

                self.assertTrue(multisig_tx.trusted)
                self.assertEqual(
                    list(multisig_tx.confirmations.values_list("owner", flat=True)),
                    [owner],
                )
                sent_event_types = get_sent_event_types(send_event_mock)
                # Not an exact count: `MultisigTransactionFactory` saves twice, and
                # the second save publishes the trusted transaction again
                self.assertIn(
                    TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name,
                    sent_event_types,
                )

    def test_approve_hash_replaces_confirmation_made_on_another_safe(self):
        """
        A confirmation of the owner made on another Safe for the same hash does not
        block the owner's ``approveHash`` on the transaction's Safe
        """
        owner = Account.create().address
        safe_status = SafeLastStatusFactory(owners=[owner])
        other_safe_status = SafeLastStatusFactory(owners=[owner])
        multisig_tx = MultisigTransactionFactory(
            safe=safe_status.address, trusted=False, ethereum_tx=None
        )
        safe_tx_hash = to_0x_hex_str(HexBytes(multisig_tx.safe_tx_hash))
        self._process_approve_hash(
            other_safe_status.address, owner, safe_tx_hash, False
        )
        self.assertFalse(multisig_tx.confirmations.exists())

        self._process_approve_hash(safe_status.address, owner, safe_tx_hash, False)

        multisig_confirmation = MultisigConfirmation.objects.get(
            multisig_transaction_hash=safe_tx_hash, owner=owner
        )
        self.assertEqual(multisig_confirmation.safe_address, safe_status.address)
        self.assertEqual(multisig_confirmation.multisig_transaction_id, safe_tx_hash)
        multisig_tx.refresh_from_db()
        self.assertTrue(multisig_tx.trusted)

    def test_approve_hash_links_ethereum_tx_only_for_transaction_safe(self):
        """
        An ``approveHash`` links its ethereum tx to an existing confirmation of the
        owner only when it is made on the transaction's Safe
        """
        owner = Account.create().address
        safe_status = SafeLastStatusFactory(owners=[owner])
        other_safe_status = SafeLastStatusFactory(owners=[owner])
        multisig_tx = MultisigTransactionFactory(
            safe=safe_status.address, ethereum_tx=None
        )
        safe_tx_hash = to_0x_hex_str(HexBytes(multisig_tx.safe_tx_hash))
        [(multisig_confirmation, _)] = (
            MultisigConfirmation.objects.get_or_create_for_transaction(
                multisig_tx,
                {
                    owner: {
                        "signature": HexBytes("0x" + "01" * 65),
                        "signature_type": SafeSignatureType.EOA.value,
                    }
                },
            )
        )

        self._process_approve_hash(
            other_safe_status.address, owner, safe_tx_hash, False
        )
        multisig_confirmation.refresh_from_db()
        self.assertIsNone(multisig_confirmation.ethereum_tx_id)

        self._process_approve_hash(safe_status.address, owner, safe_tx_hash, False)
        multisig_confirmation.refresh_from_db()
        self.assertIsNotNone(multisig_confirmation.ethereum_tx_id)

    def test_exec_transaction_replaces_confirmation_made_on_another_safe(self):
        """
        A confirmation of a signer made on another Safe for the executed hash is
        replaced by the confirmation of the execution signature
        """
        exec_decoded_tx = InternalTxDecodedFactory(
            function_name="execTransaction", internal_tx__value=0
        )
        exec_arguments = exec_decoded_tx.arguments
        # The default `execTransaction` signature is an approved hash of this owner
        signer = fast_to_checksum_address("0x2d8d6cafa6b8b7eed96c3711734d24df40c121e7")
        safe_status = SafeLastStatusFactory(
            address=exec_decoded_tx.internal_tx._from, owners=[signer], nonce=0
        )
        safe_tx_hash = to_0x_hex_str(
            SafeTx(
                None,
                safe_status.address,
                exec_arguments["to"],
                exec_arguments["value"],
                exec_arguments["data"],
                exec_arguments["operation"],
                exec_arguments["safeTxGas"],
                exec_arguments["baseGas"],
                exec_arguments["gasPrice"],
                exec_arguments["gasToken"],
                exec_arguments["refundReceiver"],
                safe_nonce=0,
                safe_version=self.tx_processor.get_safe_version_from_master_copy(
                    safe_status.master_copy
                )
                or "1.3.0",
                chain_id=self.ethereum_client.get_chain_id(),
            ).safe_tx_hash
        )
        other_safe_address = Account.create().address
        SafeLastStatusFactory(address=other_safe_address, owners=[signer])
        self._process_approve_hash(other_safe_address, signer, safe_tx_hash, False)

        self.tx_processor.process_decoded_transactions([exec_decoded_tx])

        multisig_confirmation = MultisigConfirmation.objects.get(
            multisig_transaction_hash=safe_tx_hash, owner=signer
        )
        self.assertEqual(multisig_confirmation.multisig_transaction_id, safe_tx_hash)
        self.assertEqual(multisig_confirmation.safe_address, safe_status.address)
        self.assertIsNone(multisig_confirmation.ethereum_tx_id)

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
            tx_processor.is_failed(ethereum_tx, to_0x_hex_str(fast_keccak_text("hola")))
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
            tx_processor.is_failed(ethereum_tx, to_0x_hex_str(fast_keccak_text("hola")))
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
            tx_processor.is_failed(ethereum_tx, to_0x_hex_str(fast_keccak_text("hola")))
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
        with self.assertRaises(
            CannotFindPreviousTrace
        ):  # trace_transaction not supported
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

        with self.assertRaises(ModuleCannotBeDisabled):
            safe_tx_processor.process_decoded_transaction(disable_module_tx_decoded)

        enable_module_tx_decoded = InternalTxDecodedFactory(
            function_name="enableModule",
            module=module,
            internal_tx___from=safe_address,
            internal_tx__value=0,
        )
        self.assertTrue(
            safe_tx_processor.process_decoded_transaction(enable_module_tx_decoded)
        )
        safe_last_status = SafeLastStatus.objects.get(address=safe_address)
        self.assertEqual(safe_last_status.enabled_modules, [module])
        self.assertTrue(
            safe_tx_processor.process_decoded_transaction(disable_module_tx_decoded)
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
