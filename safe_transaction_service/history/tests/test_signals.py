from datetime import timedelta
from unittest import mock

from django.db.models.signals import post_save
from django.test import TestCase

import factory

from gnosis.eth import EthereumNetwork

from safe_transaction_service.notifications.tasks import send_notification_task

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


class TestSignals(TestCase):
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

    @factory.django.mute_signals(post_save)
    def test_process_webhook(self):
        multisig_confirmation = MultisigConfirmationFactory()
        with mock.patch.object(send_webhook_task, "apply_async") as webhook_task_mock:
            with mock.patch.object(
                send_notification_task, "apply_async"
            ) as send_notification_task_mock:
                process_webhook(MultisigConfirmation, multisig_confirmation, True)
                webhook_task_mock.assert_called()
                send_notification_task_mock.assert_called()

        multisig_confirmation.created -= timedelta(minutes=75)
        with mock.patch.object(send_webhook_task, "apply_async") as webhook_task_mock:
            with mock.patch.object(
                send_notification_task, "apply_async"
            ) as send_notification_task_mock:
                process_webhook(MultisigConfirmation, multisig_confirmation, True)
                webhook_task_mock.assert_not_called()
                send_notification_task_mock.assert_not_called()

    @factory.django.mute_signals(post_save)
    def test_is_relevant_notification(self):
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

        multisig_tx = MultisigTransactionFactory()
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
