from django.test import TestCase

from safe_transaction_service.history.models import (MultisigConfirmation,
                                                     MultisigTransaction,
                                                     WebHookType)
from safe_transaction_service.history.signals import build_webhook_payload

from ...history.tests.factories import (MultisigConfirmationFactory,
                                        MultisigTransactionFactory)
from ..tasks import filter_notification


class TestViews(TestCase):
    def test_filter_notification(self):
        multisig_confirmation = MultisigConfirmationFactory()
        confirmation_notification = build_webhook_payload(MultisigConfirmation, multisig_confirmation)
        # Confirmations for executed transaction should be filtered out
        self.assertFalse(filter_notification(confirmation_notification))
        multisig_confirmation.multisig_transaction.ethereum_tx.block = None
        multisig_confirmation.multisig_transaction.ethereum_tx.save()
        confirmation_notification = build_webhook_payload(MultisigConfirmation, multisig_confirmation)
        # All confirmations are disabled for now
        # self.assertTrue(filter_notification(confirmation_notification))
        self.assertFalse(filter_notification(confirmation_notification))

        # Pending multisig transaction should be filtered out
        multisig_transaction = MultisigTransactionFactory()
        transaction_notification = build_webhook_payload(MultisigTransaction, multisig_transaction)
        self.assertTrue(filter_notification(transaction_notification))

        multisig_transaction.ethereum_tx = None
        multisig_transaction.save()
        pending_transaction_notification = build_webhook_payload(MultisigTransaction, multisig_transaction)
        self.assertNotEqual(multisig_transaction, pending_transaction_notification)
        self.assertFalse(filter_notification(pending_transaction_notification ))
