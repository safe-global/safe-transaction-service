from unittest import mock

from django.test import TestCase

from eth_account import Account
from web3 import Web3

from safe_transaction_service.history.models import (EthereumTxCallType,
                                                     EthereumTxType,
                                                     InternalTx,
                                                     MultisigConfirmation,
                                                     MultisigTransaction,
                                                     WebHookType)
from safe_transaction_service.history.signals import build_webhook_payload
from safe_transaction_service.history.tests.factories import (
    InternalTxFactory, MultisigConfirmationFactory, MultisigTransactionFactory,
    SafeContractFactory, SafeStatusFactory)

from ..tasks import (DuplicateNotification, filter_notification,
                     send_notification_owner_task, send_notification_task)
from .factories import FirebaseDeviceOwnerFactory


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

        # Incoming transaction to a Safe must be filtered out if it was triggered by that same Safe
        internal_tx = InternalTxFactory(
            value=5,
            tx_type=EthereumTxType.CALL.value,
            call_type=EthereumTxCallType.CALL.value
        )
        internal_tx_payload = build_webhook_payload(InternalTx, internal_tx)
        self.assertEqual(internal_tx_payload['address'], internal_tx.to)
        self.assertTrue(filter_notification(internal_tx_payload))
        MultisigTransactionFactory(safe=internal_tx.to, ethereum_tx=internal_tx.ethereum_tx)
        self.assertFalse(filter_notification(internal_tx_payload))

    def test_send_notification_owner_task(self):
        from ..tasks import logger as task_logger
        safe_contract = SafeContractFactory()
        safe_address = safe_contract.address
        threshold = 2
        owners = [Account.create().address for _ in range(2)]
        safe_tx_hash = Web3.keccak(text='hola').hex()
        with self.assertLogs(logger=task_logger) as cm:
            self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (0, 0))
            self.assertIn('Cannot find threshold information', cm.output[0])

        safe_status = SafeStatusFactory(address=safe_address, threshold=1, owners=owners)
        with self.assertLogs(logger=task_logger) as cm:
            self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (0, 0))
            self.assertIn('No need to send confirmation notification for ', cm.output[0])

        safe_status.threshold = threshold
        safe_status.save(update_fields=['threshold'])
        with self.assertLogs(logger=task_logger) as cm:
            self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (0, 0))
            self.assertIn('No cloud messaging tokens found', cm.output[0])

        firebase_device_owner_factories = [FirebaseDeviceOwnerFactory(owner=owner) for owner in owners]
        # Notification is not sent to both owners as they are not related to the safe address
        self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (0, 0))

        for firebase_device_owner in firebase_device_owner_factories:
            firebase_device_owner.firebase_device.safes.add(safe_contract)
        self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (2, 0))

        # Duplicated notifications are not sent
        with self.assertLogs(logger=task_logger) as cm:
            self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (0, 0))
            self.assertIn('Duplicated notification', cm.output[0])

        # Disable duplicated detection
        with mock.patch.object(DuplicateNotification, 'is_duplicated', autospec=True, return_value=False):
            self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (2, 0))

            # Add one confirmation for that transaction and other random confirmation for other transaction
            # to check that they don't influence each other
            multisig_confirmation = MultisigConfirmationFactory(owner=owners[0],
                                                                multisig_transaction__safe_tx_hash=safe_tx_hash)
            MultisigConfirmationFactory(owner=owners[1])  # Not related multisig transaction

            # Just one transaction sent, as owners[0] already confirmed
            self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (1, 0))

            # Reach the threshold with an unrelated owner
            MultisigConfirmationFactory(multisig_transaction=multisig_confirmation.multisig_transaction)
            with self.assertLogs(logger=task_logger) as cm:
                self.assertEqual(send_notification_owner_task(safe_address, safe_tx_hash), (0, 0))
                self.assertIn('does not require more confirmations', cm.output[0])

    def test_send_notification_owner_task_called(self):
        safe_address = Account.create().address
        safe_tx_hash = Web3.keccak(text='hola').hex()
        payload = {
            'address': safe_address,
            'type': WebHookType.PENDING_MULTISIG_TRANSACTION.name,
            'safeTxHash': safe_tx_hash,
        }

        with mock.patch(
                'safe_transaction_service.notifications.tasks.send_notification_owner_task.delay'
        ) as send_notification_owner_task_mock:
            send_notification_owner_task_mock.assert_not_called()
            send_notification_task.delay(safe_address, payload)
            send_notification_owner_task_mock.assert_called_with(safe_address, safe_tx_hash)
