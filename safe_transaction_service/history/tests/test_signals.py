from datetime import timedelta

from django.db.models.signals import post_save
from django.test import TestCase

import factory

from ..models import (EthereumEvent, InternalTx, MultisigConfirmation,
                      MultisigTransaction, WebHookType)
from ..signals import build_webhook_payload, is_valid_webhook
from .factories import (EthereumEventFactory, InternalTxFactory,
                        MultisigConfirmationFactory,
                        MultisigTransactionFactory)


class TestSignals(TestCase):
    @factory.django.mute_signals(post_save)
    def test_build_webhook_payload(self):
        self.assertEqual(build_webhook_payload(EthereumEvent, EthereumEventFactory())['type'],
                         WebHookType.INCOMING_TOKEN.name)
        self.assertEqual(build_webhook_payload(InternalTx, InternalTxFactory())['type'],
                         WebHookType.INCOMING_ETHER.name)
        self.assertEqual(build_webhook_payload(MultisigConfirmation, MultisigConfirmationFactory())['type'],
                         WebHookType.NEW_CONFIRMATION.name)
        self.assertEqual(build_webhook_payload(MultisigTransaction, MultisigTransactionFactory())['type'],
                         WebHookType.EXECUTED_MULTISIG_TRANSACTION.name)
        self.assertEqual(build_webhook_payload(MultisigTransaction,
                                               MultisigTransactionFactory(ethereum_tx=None))['type'],
                         WebHookType.PENDING_MULTISIG_TRANSACTION.name)

    @factory.django.mute_signals(post_save)
    def test_is_valid_webhook(self):
        multisig_confirmation = MultisigConfirmationFactory()
        self.assertFalse(is_valid_webhook(multisig_confirmation.__class__, multisig_confirmation, created=False))
        self.assertTrue(is_valid_webhook(multisig_confirmation.__class__, multisig_confirmation, created=True))
        multisig_confirmation.created -= timedelta(minutes=15)
        self.assertFalse(is_valid_webhook(multisig_confirmation.__class__, multisig_confirmation, created=True))

        multisig_tx = MultisigTransactionFactory()
        self.assertTrue(is_valid_webhook(multisig_tx.__class__, multisig_tx, created=False))
        multisig_tx.created -= timedelta(minutes=15)
        self.assertTrue(is_valid_webhook(multisig_tx.__class__, multisig_tx, created=False))
        multisig_tx.modified -= timedelta(minutes=15)
        self.assertFalse(is_valid_webhook(multisig_tx.__class__, multisig_tx, created=False))
