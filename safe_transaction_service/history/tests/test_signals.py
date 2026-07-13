# SPDX-License-Identifier: FSL-1.1-MIT
import datetime
from datetime import timedelta
from unittest import mock
from unittest.mock import MagicMock

from django.db.models.signals import post_save
from django.test import TestCase
from django.utils import timezone

import factory
from hexbytes import HexBytes
from safe_eth.eth import EthereumNetwork
from safe_eth.eth.utils import fast_keccak_text
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from ...events.services.queue_service import QueueService
from ...safe_messages.models import SafeMessage, SafeMessageConfirmation
from ...safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)
from ...tokens.services import TokenServiceProvider
from ...tokens.tests.factories import TokenFactory
from ..helpers import build_transfer_unique_id
from ..models import (
    ERC20Transfer,
    ERC721Transfer,
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    TransactionServiceEventType,
    post_bulk_create,
)
from ..services.event_service import set_safe_membership
from ..signals import (
    _process_event,
    build_event_payload,
    is_relevant_event,
)
from .factories import (
    ERC20TransferFactory,
    ERC721TransferFactory,
    InternalTxFactory,
    ModuleTransactionFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractDelegateFactory,
    SafeContractFactory,
)


class TestSignals(SafeTestCaseMixin, TestCase):
    @staticmethod
    def _annotated(instance):
        # Mark both sides as tracked Safes so both directional events are emitted (the
        # default for these structural assertions; gating is covered by dedicated tests).
        set_safe_membership(instance, to_is_a_safe=True, from_is_a_safe=True)
        return instance

    @factory.django.mute_signals(post_save)
    def test_build_message_payload(self):
        self.assertEqual(
            [
                payload["type"]
                for payload in build_event_payload(
                    ERC20Transfer, self._annotated(ERC20TransferFactory())
                )
            ],
            [
                TransactionServiceEventType.INCOMING_TOKEN.name,
                TransactionServiceEventType.OUTGOING_TOKEN.name,
            ],
        )
        self.assertEqual(
            [
                payload["type"]
                for payload in build_event_payload(
                    InternalTx, self._annotated(InternalTxFactory())
                )
            ],
            [
                TransactionServiceEventType.INCOMING_ETHER.name,
                TransactionServiceEventType.OUTGOING_ETHER.name,
            ],
        )
        self.assertEqual(
            [
                payload["chainId"]
                for payload in build_event_payload(
                    ERC20Transfer, self._annotated(ERC20TransferFactory())
                )
            ],
            [str(EthereumNetwork.GANACHE.value), str(EthereumNetwork.GANACHE.value)],
        )

        # NEW_CONFIRMATION: off-chain, timestamp from `created`
        confirmation = MultisigConfirmationFactory()
        payload = build_event_payload(MultisigConfirmation, confirmation)[0]
        self.assertEqual(
            payload["type"], TransactionServiceEventType.NEW_CONFIRMATION.name
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))
        self.assertEqual(payload["timestamp"], int(confirmation.created.timestamp()))

        # EXECUTED_MULTISIG_TRANSACTION is on-chain (tier 2): no timestamp yet
        payload = build_event_payload(
            MultisigTransaction, MultisigTransactionFactory()
        )[0]
        self.assertEqual(
            payload["type"],
            TransactionServiceEventType.EXECUTED_MULTISIG_TRANSACTION.name,
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))
        self.assertNotIn("timestamp", payload)

        # PENDING_MULTISIG_TRANSACTION: off-chain, timestamp from `created`
        pending_multisig_tx = MultisigTransactionFactory(ethereum_tx=None)
        payload = build_event_payload(MultisigTransaction, pending_multisig_tx)[0]
        self.assertEqual(
            payload["type"],
            TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name,
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))
        self.assertEqual(
            payload["timestamp"], int(pending_multisig_tx.created.timestamp())
        )

        # DELETED_MULTISIG_TRANSACTION: off-chain, fired on post_delete, timestamp is
        # the current (deletion) time
        deleted_multisig_tx = MultisigTransactionFactory(ethereum_tx=None)
        delete_time = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
        with mock.patch.object(timezone, "now", return_value=delete_time):
            payload = build_event_payload(
                MultisigTransaction,
                deleted_multisig_tx,
                deleted=True,
            )[0]
        self.assertEqual(
            payload["type"],
            TransactionServiceEventType.DELETED_MULTISIG_TRANSACTION.name,
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))
        self.assertEqual(payload["timestamp"], int(delete_time.timestamp()))

        # MODULE_TRANSACTION: on-chain, timestamp from the related InternalTx block time
        module_tx = ModuleTransactionFactory()
        payload = build_event_payload(ModuleTransaction, module_tx)[0]
        self.assertEqual(
            payload["type"], TransactionServiceEventType.MODULE_TRANSACTION.name
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))
        self.assertEqual(
            payload["timestamp"], int(module_tx.internal_tx.timestamp.timestamp())
        )

        safe_address = self.deploy_test_safe().address
        safe_message = SafeMessageFactory(safe=safe_address)
        payload = build_event_payload(SafeMessage, safe_message)[0]
        self.assertEqual(
            payload["type"], TransactionServiceEventType.MESSAGE_CREATED.name
        )
        self.assertEqual(payload["address"], safe_address)
        self.assertEqual(payload["messageHash"], safe_message.message_hash)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))
        self.assertEqual(payload["timestamp"], int(safe_message.created.timestamp()))

        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        payload = build_event_payload(
            SafeMessageConfirmation,
            safe_message_confirmation,
        )[0]
        self.assertEqual(
            payload["type"], TransactionServiceEventType.MESSAGE_CONFIRMATION.name
        )
        self.assertEqual(payload["address"], safe_address)
        self.assertEqual(payload["messageHash"], safe_message.message_hash)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))
        self.assertEqual(
            payload["timestamp"], int(safe_message_confirmation.created.timestamp())
        )

    @factory.django.mute_signals(post_save)
    def test_build_event_payload_transfer_id_and_timestamp(self):
        # Token transfer: `id` uses the log_index scheme, both directional payloads
        # share the same `id` and `timestamp` (Unix epoch seconds, int)
        transfer = self._annotated(ERC20TransferFactory())
        expected_id = build_transfer_unique_id(
            HexBytes(transfer.ethereum_tx_id), log_index=transfer.log_index
        )
        expected_timestamp = int(transfer.timestamp.timestamp())
        payloads = build_event_payload(ERC20Transfer, transfer)
        self.assertEqual(len(payloads), 2)
        for payload in payloads:
            self.assertEqual(payload["id"], expected_id)
            self.assertEqual(payload["timestamp"], expected_timestamp)
            self.assertIsInstance(payload["timestamp"], int)

        # Ether transfer: `id` uses the trace_address scheme
        internal_tx = self._annotated(InternalTxFactory())
        expected_id = build_transfer_unique_id(
            HexBytes(internal_tx.ethereum_tx_id),
            trace_address=internal_tx.trace_address,
        )
        expected_timestamp = int(internal_tx.timestamp.timestamp())
        payloads = build_event_payload(InternalTx, internal_tx)
        self.assertEqual(len(payloads), 2)
        for payload in payloads:
            self.assertEqual(payload["id"], expected_id)
            self.assertEqual(payload["timestamp"], expected_timestamp)
            self.assertIsInstance(payload["timestamp"], int)

    def test_build_transfer_unique_id_requires_exactly_one_identifier(self):
        tx_hash = HexBytes("0x" + "ab" * 32)
        # Neither identifier provided
        with self.assertRaises(ValueError):
            build_transfer_unique_id(tx_hash)
        # Both identifiers provided
        with self.assertRaises(ValueError):
            build_transfer_unique_id(tx_hash, log_index=0, trace_address="0")

    EVENT_SERVICE_LOGGER = "safe_transaction_service.history.services.event_service"

    @factory.django.mute_signals(post_save)
    def test_build_event_payload_token_gating(self):
        # Only the directional event whose side is a tracked Safe is emitted
        cases = [
            (
                True,
                True,
                [
                    TransactionServiceEventType.INCOMING_TOKEN.name,
                    TransactionServiceEventType.OUTGOING_TOKEN.name,
                ],
            ),
            (True, False, [TransactionServiceEventType.INCOMING_TOKEN.name]),
            (False, True, [TransactionServiceEventType.OUTGOING_TOKEN.name]),
            (False, False, []),  # router->router: emit neither, silently
        ]
        for to_is_a_safe, from_is_a_safe, expected in cases:
            with self.subTest(to=to_is_a_safe, from_=from_is_a_safe):
                transfer = ERC20TransferFactory()
                set_safe_membership(
                    transfer, to_is_a_safe=to_is_a_safe, from_is_a_safe=from_is_a_safe
                )
                with self.assertNoLogs(self.EVENT_SERVICE_LOGGER, level="ERROR"):
                    payloads = build_event_payload(ERC20Transfer, transfer)
                self.assertEqual([p["type"] for p in payloads], expected)

    @factory.django.mute_signals(post_save)
    def test_build_event_payload_token_trusted(self):
        self.addCleanup(TokenServiceProvider.del_singleton)
        for sender, transfer_factory in (
            (ERC20Transfer, ERC20TransferFactory),
            (ERC721Transfer, ERC721TransferFactory),
        ):
            with self.subTest(sender=sender):
                # An unknown / non-trusted token is flagged as not trusted
                TokenServiceProvider.del_singleton()
                transfer = self._annotated(transfer_factory())
                payloads = build_event_payload(sender, transfer)
                self.assertEqual([p["trusted"] for p in payloads], [False, False])

                # A trusted token is flagged as trusted on both directional payloads
                TokenServiceProvider.del_singleton()
                trusted_transfer = self._annotated(transfer_factory())
                TokenFactory(address=trusted_transfer.address, trusted=True)
                payloads = build_event_payload(sender, trusted_transfer)
                self.assertEqual([p["trusted"] for p in payloads], [True, True])

    @factory.django.mute_signals(post_save)
    def test_build_event_payload_ether_gating(self):
        cases = [
            (
                True,
                True,
                [
                    TransactionServiceEventType.INCOMING_ETHER.name,
                    TransactionServiceEventType.OUTGOING_ETHER.name,
                ],
            ),
            (True, False, [TransactionServiceEventType.INCOMING_ETHER.name]),
            (False, True, [TransactionServiceEventType.OUTGOING_ETHER.name]),
            (False, False, []),
        ]
        for to_is_a_safe, from_is_a_safe, expected in cases:
            with self.subTest(to=to_is_a_safe, from_=from_is_a_safe):
                internal_tx = InternalTxFactory()
                set_safe_membership(
                    internal_tx,
                    to_is_a_safe=to_is_a_safe,
                    from_is_a_safe=from_is_a_safe,
                )
                with self.assertNoLogs(self.EVENT_SERVICE_LOGGER, level="ERROR"):
                    payloads = build_event_payload(InternalTx, internal_tx)
                self.assertEqual([p["type"] for p in payloads], expected)

    @factory.django.mute_signals(post_save)
    def test_build_event_payload_missing_metadata_logs_error(self):
        # Unannotated instances must emit nothing and log an error pinpointing the transfer
        transfer = ERC20TransferFactory()  # not annotated
        with self.assertLogs(self.EVENT_SERVICE_LOGGER, level="ERROR") as cm:
            self.assertEqual(build_event_payload(ERC20Transfer, transfer), [])
        self.assertIn("Lacking metadata", cm.output[0])
        self.assertIn(to_0x_hex_str(HexBytes(transfer.ethereum_tx_id)), cm.output[0])
        self.assertIn(str(transfer.log_index), cm.output[0])

        internal_tx = InternalTxFactory()  # not annotated, is_ether_transfer
        with self.assertLogs(self.EVENT_SERVICE_LOGGER, level="ERROR") as cm:
            self.assertEqual(build_event_payload(InternalTx, internal_tx), [])
        self.assertIn(to_0x_hex_str(HexBytes(internal_tx.ethereum_tx_id)), cm.output[0])
        self.assertIn(internal_tx.trace_address, cm.output[0])

    @factory.django.mute_signals(post_save)
    def test_is_relevant_event_multisig_confirmation(self):
        multisig_confirmation = MultisigConfirmationFactory()
        self.assertFalse(
            is_relevant_event(
                multisig_confirmation.__class__, multisig_confirmation, created=False
            )
        )
        self.assertTrue(
            is_relevant_event(
                multisig_confirmation.__class__, multisig_confirmation, created=True
            )
        )
        multisig_confirmation.created -= timedelta(minutes=75)
        self.assertFalse(
            is_relevant_event(
                multisig_confirmation.__class__, multisig_confirmation, created=True
            )
        )

    @factory.django.mute_signals(post_save)
    def test_is_relevant_event_multisig_transaction(self):
        multisig_tx = MultisigTransactionFactory(trusted=False)
        self.assertFalse(
            is_relevant_event(multisig_tx.__class__, multisig_tx, created=False)
        )

        multisig_tx.trusted = True
        self.assertTrue(
            is_relevant_event(multisig_tx.__class__, multisig_tx, created=False)
        )

        multisig_tx.created -= timedelta(minutes=75)
        self.assertTrue(
            is_relevant_event(multisig_tx.__class__, multisig_tx, created=False)
        )
        multisig_tx.modified -= timedelta(minutes=75)
        self.assertFalse(
            is_relevant_event(multisig_tx.__class__, multisig_tx, created=False)
        )

    @mock.patch.object(QueueService, "send_events")
    def test_signals_are_correctly_fired(self, send_events_mock: MagicMock):
        # Not trusted txs should not fire any event
        with self.captureOnCommitCallbacks(execute=True):
            MultisigTransactionFactory(trusted=False)
        send_events_mock.assert_not_called()

        # Trusted txs should fire an event
        with self.captureOnCommitCallbacks(execute=True):
            multisig_tx: MultisigTransaction = MultisigTransactionFactory(trusted=True)
        pending_multisig_transaction_payload = {
            "address": multisig_tx.safe,
            "type": TransactionServiceEventType.EXECUTED_MULTISIG_TRANSACTION.name,
            "safeTxHash": multisig_tx.safe_tx_hash,
            "to": multisig_tx.to,
            "data": (
                to_0x_hex_str(HexBytes(multisig_tx.data)) if multisig_tx.data else None
            ),
            "failed": "false",
            "isFailed": False,
            "txHash": multisig_tx.ethereum_tx_id,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_events_mock.assert_called_with([pending_multisig_transaction_payload])

        # Deleting a tx should fire an event timestamped at the deletion time.
        # The payload must be built before commit, while the row still exists
        send_events_mock.reset_mock()
        safe_tx_hash = multisig_tx.safe_tx_hash
        delete_time = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
        with mock.patch.object(timezone, "now", return_value=delete_time):
            with self.captureOnCommitCallbacks(execute=True):
                multisig_tx.delete()

        deleted_multisig_transaction_payload = {
            "timestamp": int(delete_time.timestamp()),
            "address": multisig_tx.safe,
            "type": TransactionServiceEventType.DELETED_MULTISIG_TRANSACTION.name,
            "safeTxHash": safe_tx_hash,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_events_mock.assert_called_with([deleted_multisig_transaction_payload])

    @factory.django.mute_signals(post_save)
    @mock.patch("safe_transaction_service.history.signals.get_queue_service")
    def test_queue_service_not_resolved_without_payloads(
        self, get_queue_service_mock: MagicMock
    ):
        # A transfer where neither side is a tracked Safe emits no payloads.
        # The queue service must not even be resolved then: its construction
        # connects to the broker and raises if it is unavailable, which would
        # break the write for an event that was never going to be sent
        transfer = ERC20TransferFactory()
        set_safe_membership(transfer, to_is_a_safe=False, from_is_a_safe=False)

        with self.captureOnCommitCallbacks(execute=True):
            _process_event(ERC20Transfer, transfer, created=True, deleted=False)

        get_queue_service_mock.assert_not_called()

    @mock.patch.object(QueueService, "send_events")
    def test_events_are_sent_only_on_commit(self, send_events_mock: MagicMock):
        # Events must never be published while the transaction is still open
        # (consumers would query the API before the data is visible), only
        # once it commits. If the transaction rolls back, Django discards the
        # `on_commit` callbacks and nothing is published
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            MultisigTransactionFactory(trusted=True)
            send_events_mock.assert_not_called()

        self.assertGreaterEqual(len(callbacks), 1)
        send_events_mock.assert_called()

    @mock.patch.object(QueueService, "send_events")
    def test_pending_event_emitted_when_tx_bound_to_existing_confirmations(
        self, send_events_mock: MagicMock
    ):
        """
        When a MultisigTransaction is created with trusted=False but unlinked
        confirmations already exist, bind_confirmation promotes it to trusted=True
        in the DB. The in-memory instance must also be updated so the subsequent
        process_event signal handler emits PENDING_MULTISIG_TRANSACTION.
        """
        known_hash = to_0x_hex_str(fast_keccak_text("bind-test-tx-pending-event"))

        # Create the confirmation before the transaction exists (unlinked).
        # Mute signals so this creation doesn't interfere with the mock state.
        with factory.django.mute_signals(post_save):
            MultisigConfirmationFactory(
                multisig_transaction=None,
                multisig_transaction_hash=known_hash,
            )
        send_events_mock.assert_not_called()

        # Now create the transaction with trusted=False.  bind_confirmation should
        # find the orphaned confirmation, set trusted=True in the DB *and* on the
        # in-memory instance so process_event can emit the notification.
        with self.captureOnCommitCallbacks(execute=True):
            MultisigTransactionFactory(
                trusted=False, ethereum_tx=None, safe_tx_hash=known_hash
            )

        emitted_types = [
            payload["type"]
            for call in send_events_mock.call_args_list
            for payload in call.args[0]
        ]
        self.assertIn(
            TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name, emitted_types
        )

    @mock.patch.object(QueueService, "send_events")
    def test_delegates_signals_are_correctly_fired(self, send_events_mock: MagicMock):
        # New delegate should fire an event
        with self.captureOnCommitCallbacks(execute=True):
            delegate_for_safe = SafeContractDelegateFactory()
        new_delegate_user_payload = {
            "type": TransactionServiceEventType.NEW_DELEGATE.name,
            "address": delegate_for_safe.safe_contract.address,
            "delegate": delegate_for_safe.delegate,
            "delegator": delegate_for_safe.delegator,
            "label": delegate_for_safe.label,
            "expiryDateSeconds": int(delegate_for_safe.expiry_date.timestamp()),
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_events_mock.assert_called_with([new_delegate_user_payload])

        with self.captureOnCommitCallbacks(execute=True):
            permanent_delegate_without_safe = SafeContractDelegateFactory(
                safe_contract=None, expiry_date=None
            )
        new_delegate_user_payload = {
            "type": TransactionServiceEventType.NEW_DELEGATE.name,
            "address": None,
            "delegate": permanent_delegate_without_safe.delegate,
            "delegator": permanent_delegate_without_safe.delegator,
            "label": permanent_delegate_without_safe.label,
            "expiryDateSeconds": None,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_events_mock.assert_called_with([new_delegate_user_payload])

        # Updated delegate should fire an event
        with self.captureOnCommitCallbacks(execute=True):
            delegate_to_update = SafeContractDelegateFactory()
        new_safe = SafeContractFactory()
        new_label = "Updated Label"
        new_expiry_date = timezone.now() + datetime.timedelta(minutes=5)
        delegate_to_update.safe_contract = new_safe
        delegate_to_update.label = new_label
        delegate_to_update.expiry_date = new_expiry_date
        with self.captureOnCommitCallbacks(execute=True):
            delegate_to_update.save()
        updated_delegate_user_payload = {
            "type": TransactionServiceEventType.UPDATED_DELEGATE.name,
            "address": new_safe.address,
            "delegate": delegate_to_update.delegate,
            "delegator": delegate_to_update.delegator,
            "label": new_label,
            "expiryDateSeconds": int(new_expiry_date.timestamp()),
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_events_mock.assert_called_with([updated_delegate_user_payload])

        # Deleted delegate should fire an event
        with self.captureOnCommitCallbacks(execute=True):
            delegate_to_delete = SafeContractDelegateFactory()
        with self.captureOnCommitCallbacks(execute=True):
            delegate_to_delete.delete()
        deleted_delegate_user_payload = {
            "type": TransactionServiceEventType.DELETED_DELEGATE.name,
            "address": delegate_to_delete.safe_contract.address,
            "delegate": delegate_to_delete.delegate,
            "delegator": delegate_to_delete.delegator,
            "label": delegate_to_delete.label,
            "expiryDateSeconds": int(delegate_to_delete.expiry_date.timestamp()),
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_events_mock.assert_called_with([deleted_delegate_user_payload])

    @factory.django.mute_signals(post_save)
    @mock.patch(
        "safe_transaction_service.history.signals.remove_cache_view_for_addresses"
    )
    @mock.patch("safe_transaction_service.history.signals.build_event_payload")
    @mock.patch.object(QueueService, "send_events")
    def test_irrelevant_events_skip(
        self,
        send_events_mock: MagicMock,
        build_event_payload_mock: MagicMock,
        remove_cache_mock: MagicMock,
    ):
        # Old events are not relevant and should short-circuit before payload work.
        # Cache invalidation still happens: eagerly, and again on commit
        tx = ERC20TransferFactory(timestamp=timezone.now() - timedelta(minutes=120))

        with self.captureOnCommitCallbacks(execute=True):
            _process_event(ERC20Transfer, tx, created=True, deleted=False)
            remove_cache_mock.assert_called_once()

        self.assertEqual(remove_cache_mock.call_count, 2)
        build_event_payload_mock.assert_not_called()
        send_events_mock.assert_not_called()

    @mock.patch.object(QueueService, "send_events")
    @mock.patch(
        "safe_transaction_service.history.signals.remove_cache_view_for_addresses",
        side_effect=Exception("Redis is down"),
    )
    def test_cache_invalidation_failure_does_not_block_events(
        self, remove_cache_mock: MagicMock, send_events_mock: MagicMock
    ):
        # A cache backend failure must not abort the write nor the event
        # emission — it would otherwise roll back whole indexer batches.
        # Note `remove_cache_view_for_addresses` itself never raises (this
        # mock simulates a regression in that guarantee), so the signal path
        # must tolerate it anyway
        with self.captureOnCommitCallbacks(execute=True):
            MultisigTransactionFactory(trusted=True)

        send_events_mock.assert_called()

    @factory.django.mute_signals(post_save)
    @mock.patch.object(QueueService, "send_events")
    def test_post_bulk_create_dispatch_processes_event(
        self, send_events_mock: MagicMock
    ):
        # Regression: `post_bulk_create.send(instance=..., created=True)` must reach
        # `process_event` (which absorbs Django's signal kwargs). If the receiver
        # decorators bind to a function requiring `deleted`/lacking `**kwargs`,
        # dispatch raises TypeError and breaks bulk_create.
        tx = self._annotated(ERC20TransferFactory())

        with self.captureOnCommitCallbacks(execute=True):
            post_bulk_create.send(ERC20Transfer, instance=tx, created=True)
            # Events are only published once the transaction commits
            send_events_mock.assert_not_called()

        (payloads,) = send_events_mock.call_args.args
        self.assertEqual(
            [payload["type"] for payload in payloads],
            [
                TransactionServiceEventType.INCOMING_TOKEN.name,
                TransactionServiceEventType.OUTGOING_TOKEN.name,
            ],
        )
