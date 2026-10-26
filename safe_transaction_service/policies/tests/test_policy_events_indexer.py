# SPDX-License-Identifier: FSL-1.1-MIT
import datetime
from unittest import mock

from django.conf import settings
from django.test import TestCase

from eth_abi import encode as encode_abi
from hexbytes import HexBytes
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.safe.enums import SafeOperationEnum

from safe_transaction_service.history.models import EthereumBlock
from safe_transaction_service.history.tests import factories as history_factories

from ..indexers import PolicyEventsIndexerProvider
from ..models import (
    FALLBACK_SELECTOR,
    PolicyConfirmation,
    PolicyRootInvalidation,
    PolicyRootRequest,
)
from .factories import SafePolicyGuardFactory
from .mocks.mocks_policy_events_indexer import (
    ALLOW_POLICY,
    COSIGNER,
    COSIGNER_POLICY,
    ERC20_TRANSFER_POLICY,
    GUARD,
    OTHER_SAFE,
    RECIPIENTS,
    SAFE,
    TOKEN,
    policy_guard_log_receipts,
)

ERC20_TRANSFER_SELECTOR = HexBytes("0xa9059cbb")


class TestPolicyEventsIndexer(TestCase):
    def setUp(self) -> None:
        PolicyEventsIndexerProvider.del_singleton()
        self.indexer = PolicyEventsIndexerProvider()
        # The mocked block hashes are fixed, but every test builds its blocks again
        EthereumBlock.objects.get_timestamp_by_hash.cache_clear()
        # The blocks and transactions of the events must exist, so no node call is needed.
        # A single transaction can emit more than one event, e.g. `configureImmediately`
        # with several configurations
        transactions = {
            log_receipt["transactionHash"]: log_receipt
            for log_receipt in policy_guard_log_receipts
        }
        for tx_hash, log_receipt in transactions.items():
            history_factories.EthereumTxFactory(
                tx_hash=tx_hash,
                block__block_hash=log_receipt["blockHash"],
                block__number=log_receipt["blockNumber"],
            )

    def tearDown(self) -> None:
        PolicyEventsIndexerProvider.del_singleton()

    def test_contract_events_cover_every_indexed_event(self):
        self.assertCountEqual(
            [event.event_name for event in self.indexer.contract_events],
            self.indexer.EVENT_TO_MODEL,
        )
        # One topic per event, all of them listened to
        self.assertEqual(
            len(self.indexer.events_to_listen), len(self.indexer.EVENT_TO_MODEL)
        )

    def test_process_elements(self):
        self.assertEqual(
            len(self.indexer.process_elements(policy_guard_log_receipts)), 7
        )

        self.assertEqual(PolicyConfirmation.objects.count(), 4)
        self.assertEqual(PolicyRootRequest.objects.count(), 2)
        self.assertEqual(PolicyRootInvalidation.objects.count(), 1)

    def test_process_elements_decodes_policy_confirmed(self):
        self.indexer.process_elements(policy_guard_log_receipts)

        confirmation = PolicyConfirmation.objects.get(
            safe=SAFE, target=TOKEN, policy=ERC20_TRANSFER_POLICY
        )
        self.assertEqual(confirmation.guard, GUARD)
        self.assertEqual(bytes(confirmation.selector), bytes(ERC20_TRANSFER_SELECTOR))
        self.assertEqual(confirmation.operation, SafeOperationEnum.CALL.value)
        self.assertFalse(confirmation.removed)
        self.assertFalse(confirmation.fallback)
        self.assertEqual(
            bytes(confirmation.data),
            encode_abi(
                ["(address,bool)[]"],
                [[(RECIPIENTS[0], True), (RECIPIENTS[1], False)]],
            ),
        )
        # The event is stored with the block metadata, not with the indexing time
        ethereum_tx = confirmation.ethereum_tx
        self.assertEqual(confirmation.block_number, ethereum_tx.block.number)
        self.assertEqual(confirmation.timestamp, ethereum_tx.block.timestamp)

    def test_process_elements_decodes_fallback_policy(self):
        self.indexer.process_elements(policy_guard_log_receipts)

        confirmation = PolicyConfirmation.objects.get(policy=COSIGNER_POLICY)
        self.assertEqual(confirmation.safe, SAFE)
        self.assertEqual(confirmation.target, NULL_ADDRESS)
        self.assertEqual(bytes(confirmation.selector), FALLBACK_SELECTOR)
        self.assertTrue(confirmation.fallback)
        self.assertEqual(bytes(confirmation.data), encode_abi(["address"], [COSIGNER]))

    def test_process_elements_decodes_delegate_call_policy(self):
        self.indexer.process_elements(policy_guard_log_receipts)

        confirmation = PolicyConfirmation.objects.get(policy=ALLOW_POLICY)
        self.assertEqual(confirmation.safe, OTHER_SAFE)
        self.assertEqual(confirmation.operation, SafeOperationEnum.DELEGATE_CALL.value)
        self.assertEqual(bytes(confirmation.data), b"")

    def test_process_elements_decodes_removal(self):
        self.indexer.process_elements(policy_guard_log_receipts)

        confirmation = PolicyConfirmation.objects.get(policy=NULL_ADDRESS)
        self.assertEqual(confirmation.safe, SAFE)
        self.assertEqual(confirmation.target, TOKEN)
        self.assertTrue(confirmation.removed)
        # A removal is not a fallback policy, it has a target and a selector
        self.assertFalse(confirmation.fallback)

    def test_process_elements_decodes_root_events(self):
        self.indexer.process_elements(policy_guard_log_receipts)

        invalidation = PolicyRootInvalidation.objects.get()
        request = PolicyRootRequest.objects.get(root=invalidation.root)
        self.assertEqual(request.safe, SAFE)
        self.assertEqual(request.guard, GUARD)
        # The request is what the invalidation cancelled
        self.assertEqual(invalidation.safe, request.safe)
        # `valid_from` is the event argument, `block.timestamp + DELAY`, so it is taken from
        # the log and not from the block the log belongs to
        log_receipt = next(
            receipt
            for receipt in policy_guard_log_receipts
            if receipt["transactionHash"] == HexBytes(request.ethereum_tx_id)
        )
        self.assertEqual(
            request.valid_from,
            datetime.datetime.fromtimestamp(
                self.indexer.decode_element(log_receipt)["args"]["timestamp"],
                datetime.UTC,
            ),
        )
        self.assertNotEqual(request.valid_from, request.timestamp)

    def test_process_elements_is_idempotent(self):
        self.assertEqual(
            len(self.indexer.process_elements(policy_guard_log_receipts)), 7
        )

        # Already processed events are skipped through the in memory checker
        self.assertEqual(
            len(self.indexer.process_elements(policy_guard_log_receipts)), 0
        )

        # And through the unique constraint once the checker is cleared, e.g. after a restart
        self.indexer.element_already_processed_checker.clear()
        self.assertEqual(
            len(self.indexer.process_elements(policy_guard_log_receipts)), 7
        )
        self.assertEqual(PolicyConfirmation.objects.count(), 4)
        self.assertEqual(PolicyRootRequest.objects.count(), 2)
        self.assertEqual(PolicyRootInvalidation.objects.count(), 1)

    def test_process_elements_empty(self):
        self.assertEqual(self.indexer.process_elements([]), [])

    def test_process_decoded_element_rejects_unsupported_operation(self):
        log_receipt = policy_guard_log_receipts[0]
        decoded_element = self.indexer.decode_element(log_receipt)
        # `Operation` only has CALL and DELEGATECALL, anything else is not a policy access
        decoded_element["args"]["operation"] = SafeOperationEnum.CREATE.value

        with self.assertLogs(
            "safe_transaction_service.policies.indexers", level="ERROR"
        ):
            self.assertIsNone(self.indexer._process_decoded_element(decoded_element))
        self.assertEqual(PolicyConfirmation.objects.count(), 0)

    def test_process_addresses_advances_the_cursor(self):
        guard = SafePolicyGuardFactory(address=GUARD, tx_block_number=10)

        with mock.patch.object(
            self.indexer,
            "find_relevant_elements",
            return_value=policy_guard_log_receipts,
        ):
            events, from_block, to_block, updated = self.indexer.process_addresses(
                {guard.address}, current_block_number=20
            )

        self.assertEqual(len(events), 7)
        # Close to the head the indexer rescans the last blocks, in case any was missed
        self.assertEqual(from_block, 10 - settings.ETH_EVENTS_BLOCKS_TO_REINDEX_AGAIN)
        self.assertEqual(to_block, 20)
        self.assertTrue(updated)

        guard.refresh_from_db()
        self.assertEqual(guard.tx_block_number, to_block + 1)

    def test_database_queryset_only_monitors_guards(self):
        guard = SafePolicyGuardFactory()

        self.assertEqual(list(self.indexer.database_queryset), [guard])
        self.assertEqual(self.indexer.database_field, "tx_block_number")
