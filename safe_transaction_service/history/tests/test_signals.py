from datetime import timedelta
from unittest import mock
from unittest.mock import MagicMock

from django.db.models.signals import post_save
from django.test import TestCase

import factory

from gnosis.eth import EthereumNetwork
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.notifications.tasks import send_notification_task

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
    WebHookType,
)
from ..signals import build_webhook_payload, is_relevant_notification, process_webhook
from ..tasks import send_webhook_task
from .factories import (
    ERC20TransferFactory,
    InternalTxFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
)


class TestSignals(SafeTestCaseMixin, TestCase):
    @factory.django.mute_signals(post_save)
    def test_build_webhook_payload(self):
        self.assertEqual(
            [
                payload["type"]
                for payload in build_webhook_payload(
                    ERC20Transfer, ERC20TransferFactory()
                )
            ],
            [WebHookType.INCOMING_TOKEN.name, WebHookType.OUTGOING_TOKEN.name],
        )
        self.assertEqual(
            [
                payload["type"]
                for payload in build_webhook_payload(InternalTx, InternalTxFactory())
            ],
            [WebHookType.INCOMING_ETHER.name, WebHookType.OUTGOING_ETHER.name],
        )
        self.assertEqual(
            [
                payload["chainId"]
                for payload in build_webhook_payload(
                    ERC20Transfer, ERC20TransferFactory()
                )
            ],
            [str(EthereumNetwork.GANACHE.value), str(EthereumNetwork.GANACHE.value)],
        )

        payload = build_webhook_payload(
            MultisigConfirmation, MultisigConfirmationFactory()
        )[0]
        self.assertEqual(payload["type"], WebHookType.NEW_CONFIRMATION.name)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_webhook_payload(
            MultisigTransaction, MultisigTransactionFactory()
        )[0]
        self.assertEqual(
            payload["type"], WebHookType.EXECUTED_MULTISIG_TRANSACTION.name
        )
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_webhook_payload(
            MultisigTransaction, MultisigTransactionFactory(ethereum_tx=None)
        )[0]
        self.assertEqual(payload["type"], WebHookType.PENDING_MULTISIG_TRANSACTION.name)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_webhook_payload(
            MultisigTransaction,
            MultisigTransactionFactory(ethereum_tx=None),
            deleted=True,
        )[0]
        self.assertEqual(payload["type"], WebHookType.DELETED_MULTISIG_TRANSACTION.name)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        safe_address = self.deploy_test_safe().address
        safe_message = SafeMessageFactory(safe=safe_address)
        payload = build_webhook_payload(SafeMessage, safe_message)[0]
        self.assertEqual(payload["type"], WebHookType.MESSAGE_CREATED.name)
        self.assertEqual(payload["address"], safe_address)
        self.assertEqual(payload["messageHash"], safe_message.message_hash)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

        payload = build_webhook_payload(
            SafeMessageConfirmation,
            SafeMessageConfirmationFactory(safe_message=safe_message),
        )[0]
        self.assertEqual(payload["type"], WebHookType.MESSAGE_CONFIRMATION.name)
        self.assertEqual(payload["address"], safe_address)
        self.assertEqual(payload["messageHash"], safe_message.message_hash)
        self.assertEqual(payload["chainId"], str(EthereumNetwork.GANACHE.value))

    @factory.django.mute_signals(post_save)
    @mock.patch.object(send_webhook_task, "apply_async")
    @mock.patch.object(send_notification_task, "apply_async")
    @mock.patch.object(QueueService, "send_event")
    def test_process_webhook(
        self,
        send_event_mock: MagicMock,
        webhook_task_mock: MagicMock,
        send_notification_task_mock: MagicMock,
    ):
        multisig_confirmation = MultisigConfirmationFactory()
        process_webhook(MultisigConfirmation, multisig_confirmation, True)
        webhook_task_mock.assert_called()
        send_notification_task_mock.assert_called()
        send_event_mock.assert_called()
        # reset calls
        webhook_task_mock.reset_mock()
        send_notification_task_mock.reset_mock()
        send_event_mock.reset_mock()

        multisig_confirmation.created -= timedelta(minutes=75)
        process_webhook(MultisigConfirmation, multisig_confirmation, True)
        webhook_task_mock.assert_not_called()
        send_event_mock.assert_not_called()
        send_notification_task_mock.assert_not_called()

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

    @mock.patch.object(send_webhook_task, "apply_async")
    @mock.patch.object(QueueService, "send_event")
    def test_signals_are_correctly_fired(
        self,
        send_event_mock: MagicMock,
        webhook_task_mock: MagicMock,
    ):
        # Not trusted txs should not fire any event
        MultisigTransactionFactory(trusted=False)
        webhook_task_mock.assert_not_called()
        send_event_mock.assert_not_called()

        # Trusted txs should fire an event
        multisig_tx: MultisigTransaction = MultisigTransactionFactory(trusted=True)
        pending_multisig_transaction_payload = {
            "address": multisig_tx.safe,
            "safeTxHash": multisig_tx.safe_tx_hash,
            "type": WebHookType.EXECUTED_MULTISIG_TRANSACTION.name,
            "failed": "false",
            "txHash": multisig_tx.ethereum_tx_id,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        webhook_task_mock.assert_called_with(
            args=(multisig_tx.safe, pending_multisig_transaction_payload), priority=2
        )
        send_event_mock.assert_called_with(pending_multisig_transaction_payload)

        # Deleting a tx should fire an event
        webhook_task_mock.reset_mock()
        send_event_mock.reset_mock()
        safe_tx_hash = multisig_tx.safe_tx_hash
        multisig_tx.delete()

        deleted_multisig_transaction_payload = {
            "address": multisig_tx.safe,
            "safeTxHash": safe_tx_hash,
            "type": WebHookType.DELETED_MULTISIG_TRANSACTION.name,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }

        webhook_task_mock.assert_called_with(
            args=(multisig_tx.safe, deleted_multisig_transaction_payload), priority=2
        )
        send_event_mock.assert_called_with(deleted_multisig_transaction_payload)
