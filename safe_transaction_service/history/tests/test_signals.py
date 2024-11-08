import datetime
from datetime import timedelta
from unittest import mock
from unittest.mock import MagicMock

from django.db.models.signals import post_save
from django.test import TestCase
from django.utils import timezone

import factory
from safe_eth.eth import EthereumNetwork
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from ...events.services.queue_service import QueueService
from ...safe_messages.models import SafeMessage, SafeMessageConfirmation
from ...safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)
from ..models import (
    ERC20Transfer,
    InternalTx,
    MultisigConfirmation,
    MultisigTransaction,
    TransactionServiceEventType,
)
from ..signals import build_event_payload, is_relevant_notification
from .factories import (
    ERC20TransferFactory,
    InternalTxFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractDelegateFactory,
    SafeContractFactory,
)


class TestSignals(SafeTestCaseMixin, TestCase):
    @factory.django.mute_signals(post_save)
    def test_build_message_payload(self):
        self.assertEqual(
            [
                payload["type"]
                for payload in build_event_payload(
                    ERC20Transfer, ERC20TransferFactory()
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
                for payload in build_event_payload(InternalTx, InternalTxFactory())
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
                    ERC20Transfer, ERC20TransferFactory()
                )
            ],
            [str(EthereumNetwork.GANACHE.value), str(EthereumNetwork.GANACHE.value)],
        )

        payload = build_event_payload(
            MultisigConfirmation, MultisigConfirmationFactory()
        )[0]
        self.assertEqual(
            payload["type"], TransactionServiceEventType.NEW_CONFIRMATION.name
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_event_payload(
            MultisigTransaction, MultisigTransactionFactory()
        )[0]
        self.assertEqual(
            payload["type"],
            TransactionServiceEventType.EXECUTED_MULTISIG_TRANSACTION.name,
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_event_payload(
            MultisigTransaction, MultisigTransactionFactory(ethereum_tx=None)
        )[0]
        self.assertEqual(
            payload["type"],
            TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name,
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_event_payload(
            MultisigTransaction,
            MultisigTransactionFactory(ethereum_tx=None),
            deleted=True,
        )[0]
        self.assertEqual(
            payload["type"],
            TransactionServiceEventType.DELETED_MULTISIG_TRANSACTION.name,
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        safe_address = self.deploy_test_safe().address
        safe_message = SafeMessageFactory(safe=safe_address)
        payload = build_event_payload(SafeMessage, safe_message)[0]
        self.assertEqual(
            payload["type"], TransactionServiceEventType.MESSAGE_CREATED.name
        )
        self.assertEqual(payload["address"], safe_address)
        self.assertEqual(payload["messageHash"], safe_message.message_hash)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_event_payload(
            SafeMessageConfirmation,
            SafeMessageConfirmationFactory(safe_message=safe_message),
        )[0]
        self.assertEqual(
            payload["type"], TransactionServiceEventType.MESSAGE_CONFIRMATION.name
        )
        self.assertEqual(payload["address"], safe_address)
        self.assertEqual(payload["messageHash"], safe_message.message_hash)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

    @factory.django.mute_signals(post_save)
    def test_is_relevant_notification_multisig_confirmation(self):
        multisig_confirmation = MultisigConfirmationFactory()
        self.assertFalse(
            is_relevant_notification(
                multisig_confirmation.__class__, multisig_confirmation, created=False
            )
        )
        self.assertTrue(
            is_relevant_notification(
                multisig_confirmation.__class__, multisig_confirmation, created=True
            )
        )
        multisig_confirmation.created -= timedelta(minutes=75)
        self.assertFalse(
            is_relevant_notification(
                multisig_confirmation.__class__, multisig_confirmation, created=True
            )
        )

    @factory.django.mute_signals(post_save)
    def test_is_relevant_notification_multisig_transaction(self):
        multisig_tx = MultisigTransactionFactory(trusted=False)
        self.assertFalse(
            is_relevant_notification(multisig_tx.__class__, multisig_tx, created=False)
        )

        multisig_tx.trusted = True
        self.assertTrue(
            is_relevant_notification(multisig_tx.__class__, multisig_tx, created=False)
        )

        multisig_tx.created -= timedelta(minutes=75)
        self.assertTrue(
            is_relevant_notification(multisig_tx.__class__, multisig_tx, created=False)
        )
        multisig_tx.modified -= timedelta(minutes=75)
        self.assertFalse(
            is_relevant_notification(multisig_tx.__class__, multisig_tx, created=False)
        )

    @mock.patch.object(QueueService, "send_event")
    def test_signals_are_correctly_fired(self, send_event_mock: MagicMock):
        # Not trusted txs should not fire any event
        MultisigTransactionFactory(trusted=False)
        send_event_mock.assert_not_called()

        # Trusted txs should fire an event
        multisig_tx: MultisigTransaction = MultisigTransactionFactory(trusted=True)
        pending_multisig_transaction_payload = {
            "address": multisig_tx.safe,
            "safeTxHash": multisig_tx.safe_tx_hash,
            "type": TransactionServiceEventType.EXECUTED_MULTISIG_TRANSACTION.name,
            "failed": "false",
            "txHash": multisig_tx.ethereum_tx_id,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_event_mock.assert_called_with(pending_multisig_transaction_payload)

        # Deleting a tx should fire an event
        send_event_mock.reset_mock()
        safe_tx_hash = multisig_tx.safe_tx_hash
        multisig_tx.delete()

        deleted_multisig_transaction_payload = {
            "address": multisig_tx.safe,
            "safeTxHash": safe_tx_hash,
            "type": TransactionServiceEventType.DELETED_MULTISIG_TRANSACTION.name,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_event_mock.assert_called_with(deleted_multisig_transaction_payload)

    @mock.patch.object(QueueService, "send_event")
    def test_delegates_signals_are_correctly_fired(self, send_event_mock: MagicMock):
        # New delegate should fire an event
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
        send_event_mock.assert_called_with(new_delegate_user_payload)

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
        send_event_mock.assert_called_with(new_delegate_user_payload)

        # Updated delegate should fire an event
        delegate_to_update = SafeContractDelegateFactory()
        new_safe = SafeContractFactory()
        new_label = "Updated Label"
        new_expiry_date = timezone.now() + datetime.timedelta(minutes=5)
        delegate_to_update.safe_contract = new_safe
        delegate_to_update.label = new_label
        delegate_to_update.expiry_date = new_expiry_date
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
        send_event_mock.assert_called_with(updated_delegate_user_payload)

        # Deleted delegate should fire an event
        delegate_to_delete = SafeContractDelegateFactory()
        delegate_to_delete.delete()
        updated_delegate_user_payload = {
            "type": TransactionServiceEventType.DELETED_DELEGATE.name,
            "address": delegate_to_delete.safe_contract.address,
            "delegate": delegate_to_delete.delegate,
            "delegator": delegate_to_delete.delegator,
            "label": delegate_to_delete.label,
            "expiryDateSeconds": int(delegate_to_delete.expiry_date.timestamp()),
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        send_event_mock.assert_called_with(updated_delegate_user_payload)
