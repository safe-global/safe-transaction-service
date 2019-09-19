import logging

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.safe import Safe
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from .factories import MultisigConfirmationFactory, MultisigTransactionFactory

logger = logging.getLogger(__name__)


class TestViews(SafeTestCaseMixin, APITestCase):
    def test_get_multisig_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        multisig_tx = MultisigTransactionFactory(safe=safe_address)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 0)
        self.assertEqual(response.data['results'][0]['transaction_hash'], multisig_tx.ethereum_tx.tx_hash)
        # Test camelCase
        self.assertEqual(response.json()['results'][0]['transactionHash'], multisig_tx.ethereum_tx.tx_hash)

        MultisigConfirmationFactory(multisig_transaction=multisig_tx)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 1)

    def test_post_multisig_transactions(self):
        safe_owner_1 = Account.create()
        safe_create2_tx = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe_create2_tx.safe_address
        safe = Safe(safe_address, self.ethereum_client)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        to = Account.create().address
        data = {"to": to,
                "value": 100000000000000000,
                "data": None,
                "operation": 0,
                "nonce": 0,
                "safeTxGas": 0,
                "baseGas": 0,
                "gasPrice": 0,
                "gasToken": "0x0000000000000000000000000000000000000000",
                "refundReceiver": "0x0000000000000000000000000000000000000000",
                # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
                "transactionHash": "0x57f45a05893cc426d7465c7118842b0806a3d83bc994403fa25a4a7fdc28c805",
                "sender": safe_owner_1.address,
                }
        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safeTxGas'], data['baseGas'], data['gasPrice'],
                                         data['gasToken'],
                                         data['refundReceiver'], safe_nonce=data['nonce'])
        data['contractTransactionHash'] = safe_tx.safe_tx_hash.hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 0)

        # Test confirmation with signature
        data['signature'] = safe_owner_1.signHash(safe_tx.safe_tx_hash)['signature'].hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 1)
        self.assertEqual(response.data['results'][0]['confirmations'][0]['signature'], data['signature'])

        # Sign with a random user (not owner)
        data['signature'] = Account.create().signHash(safe_tx.safe_tx_hash)['signature'].hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertIn('Signature does not match sender', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
