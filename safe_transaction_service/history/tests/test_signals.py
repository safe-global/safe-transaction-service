from django.test import TestCase

from ..models import (EthereumEvent, InternalTx, MultisigConfirmation,
                      MultisigTransaction, WebHookType)
from ..signals import build_webhook_payload
from .factories import (EthereumEventFactory, InternalTxFactory,
                        MultisigConfirmationFactory,
                        MultisigTransactionFactory)


class TestSignals(TestCase):
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
