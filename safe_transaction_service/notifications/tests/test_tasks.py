from django.test import TestCase

from eth_account import Account

from safe_transaction_service.history.models import (MultisigConfirmation,
                                                     MultisigTransaction)
from safe_transaction_service.history.signals import build_webhook_payload

from ...history.tests.factories import (MultisigConfirmationFactory,
                                        MultisigTransactionFactory)
from ..tasks import DuplicateNotification, filter_notification


class TestViews(TestCase):
    def test_duplicate_notification_manager(self):
        address = '0x1230B3d59858296A31053C1b8562Ecf89A2f888b'
        payload = {'address': '0x1230B3d59858296A31053C1b8562Ecf89A2f888b',
                   'type': 'INCOMING_TOKEN',
                   'tokenAddress': '0x63704B63Ac04f3a173Dfe677C7e3D330c347CD88',
                   'txHash': '0xd8cf5db08e4f3d43660975c8be02a079139a69c42c0ccdd157618aec9bb91b28',
                   'value': '50000000000000'}
        duplicate_notification = DuplicateNotification(address, payload)
        self.assertFalse(duplicate_notification.is_duplicated())
        self.assertFalse(duplicate_notification.is_duplicated())
        duplicate_notification.set_duplicated()
        self.assertTrue(duplicate_notification.is_duplicated())
        duplicate_notification_2 = DuplicateNotification(address, {'type': 'Different_payload'})
        self.assertFalse(duplicate_notification_2.is_duplicated())
        duplicate_notification_3 = DuplicateNotification(Account.create().address, payload)
        self.assertFalse(duplicate_notification_3.is_duplicated())

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
        self.assertFalse(filter_notification(pending_transaction_notification))
