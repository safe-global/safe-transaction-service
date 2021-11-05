from datetime import timedelta

from django.db.models.signals import post_save
from django.test import TestCase

import factory

from gnosis.eth import EthereumNetwork

from ..models import (
    ERC20Transfer,
    InternalTx,
    MultisigConfirmation,
    MultisigTransaction,
    WebHookType,
)
from ..signals import build_webhook_payload, is_valid_webhook
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
    def test_is_valid_webhook(self):
        multisig_confirmation = MultisigConfirmationFactory()
        self.assertFalse(
            is_valid_webhook(
                multisig_confirmation.__class__, multisig_confirmation, created=False
            )
        )
        self.assertTrue(
            is_valid_webhook(
                multisig_confirmation.__class__, multisig_confirmation, created=True
            )
        )
        multisig_confirmation.created -= timedelta(minutes=15)
        self.assertFalse(
            is_valid_webhook(
                multisig_confirmation.__class__, multisig_confirmation, created=True
            )
        )

        multisig_tx = MultisigTransactionFactory()
        self.assertTrue(
            is_valid_webhook(multisig_tx.__class__, multisig_tx, created=False)
        )
        multisig_tx.created -= timedelta(minutes=15)
        self.assertTrue(
            is_valid_webhook(multisig_tx.__class__, multisig_tx, created=False)
        )
        multisig_tx.modified -= timedelta(minutes=15)
        self.assertFalse(
            is_valid_webhook(multisig_tx.__class__, multisig_tx, created=False)
        )
