from datetime import timedelta
from unittest import mock
from unittest.mock import MagicMock

from django.db.models.signals import post_save
from django.test import TestCase

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
