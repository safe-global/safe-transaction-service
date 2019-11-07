import logging

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase
from web3 import Web3

from gnosis.safe import Safe
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.models import (EthereumTxCallType,
                                                     InternalTx, SafeContract)

from .factories import (EthereumEventFactory, InternalTxFactory,
                        MultisigConfirmationFactory,
                        MultisigTransactionFactory, SafeContractFactory)

logger = logging.getLogger(__name__)


class TestViews(SafeTestCaseMixin, APITestCase):
    def test_get_multisig_transaction(self):
        safe_tx_hash = Web3.sha3(text='gnosis').hex()
        response = self.client.get(reverse('v1:multisig-transaction', args=(safe_tx_hash,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        multisig_tx = MultisigTransactionFactory()
        safe_tx_hash = multisig_tx.safe_tx_hash
        response = self.client.get(reverse('v1:multisig-transaction', args=(safe_tx_hash,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['confirmations']), 0)
        self.assertTrue(Web3.isChecksumAddress(response.data['executor']))
        self.assertEqual(response.data['transaction_hash'], multisig_tx.ethereum_tx.tx_hash)
        # Test camelCase
        self.assertEqual(response.json()['transactionHash'], multisig_tx.ethereum_tx.tx_hash)

    def test_get_multisig_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        multisig_tx = MultisigTransactionFactory(safe=safe_address)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 0)
        self.assertTrue(Web3.isChecksumAddress(response.data['results'][0]['executor']))
        self.assertEqual(response.data['results'][0]['transaction_hash'], multisig_tx.ethereum_tx.tx_hash)
        # Test camelCase
        self.assertEqual(response.json()['results'][0]['transactionHash'], multisig_tx.ethereum_tx.tx_hash)

        MultisigConfirmationFactory(multisig_transaction=multisig_tx)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 1)

    def test_get_multisig_transactions_filters(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        MultisigTransactionFactory(safe=safe_address, nonce=0, ethereum_tx=None)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?nonce=0',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?nonce=1',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?executed=true',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?executed=false',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

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
        self.assertIsNone(response.data['results'][0]['executor'])
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

        # Sign with a different user that sender
        random_user_account = Account.create()
        data['signature'] = random_user_account.signHash(safe_tx.safe_tx_hash)['signature'].hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertIn('Signature does not match sender', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Sign with a random user (not owner)
        data['sender'] = random_user_account.address
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertIn('User is not an owner', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_safe_balances_view(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertIsNone(response.json()[0]['tokenAddress'])
        self.assertEqual(response.json()[0]['balance'], str(value))

        tokens_value = 12
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)

        EthereumEventFactory(address=erc20.address, to=safe_address)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.json(), [{'tokenAddress': None, 'balance': str(value)},
                                                {'tokenAddress': erc20.address, 'balance': str(tokens_value)}])

    def test_incoming_txs_view(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:incoming-transactions', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        response = self.client.get(reverse('v1:incoming-transactions', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 0)

        value = 2
        InternalTxFactory(to=safe_address, value=0)
        internal_tx = InternalTxFactory(to=safe_address, value=value)
        InternalTxFactory(to=Account.create().address, value=value)
        response = self.client.get(reverse('v1:incoming-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['value'], value)

        token_value = 6
        ethereum_event = EthereumEventFactory(to=safe_address, value=token_value)
        response = self.client.get(reverse('v1:incoming-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 2)
        self.assertCountEqual(response.json(), [
            {'transactionHash': internal_tx.ethereum_tx_id,
             'to': safe_address,
             'value': value,
             'tokenAddress': None,
             'from': internal_tx._from,
             },
            {'transactionHash': ethereum_event.ethereum_tx_id,
             'to': safe_address,
             'value': token_value,
             'tokenAddress': ethereum_event.address,
             'from': ethereum_event.arguments['from']
             }
        ])
