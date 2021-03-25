import logging
from dataclasses import asdict
from unittest import mock
from unittest.mock import MagicMock

from django.urls import reverse
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes
from rest_framework import status
from rest_framework.test import APITestCase
from web3 import Web3

from gnosis.eth.ethereum_client import ParityManager
from gnosis.safe import CannotEstimateGas, Safe
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.services.price_service import PriceService
from safe_transaction_service.tokens.tests.factories import TokenFactory

from ..exceptions import NodeConnectionError
from ..helpers import DelegateSignatureHelper
from ..models import (MultisigConfirmation, MultisigTransaction,
                      SafeContractDelegate)
from ..serializers import TransferType
from ..services import BalanceService, CollectiblesService, SafeService
from ..services.balance_service import Erc20InfoWithLogo
from ..services.collectibles_service import CollectibleWithMetadata
from .factories import (EthereumEventFactory, EthereumTxFactory,
                        InternalTxFactory, ModuleTransactionFactory,
                        MultisigConfirmationFactory,
                        MultisigTransactionFactory,
                        SafeContractDelegateFactory, SafeContractFactory,
                        SafeMasterCopyFactory, SafeStatusFactory)
from .mocks.traces import call_trace

logger = logging.getLogger(__name__)


class TestViews(SafeTestCaseMixin, APITestCase):
    def test_all_transactions_view(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

        # Factories create the models using current datetime, so as the txs are returned sorted they should be
        # in the reverse order that they were created
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        internal_tx_out = InternalTxFactory(_from=safe_address, value=5)  # Should not appear
        erc20_transfer_in = EthereumEventFactory(to=safe_address)
        erc20_transfer_out = EthereumEventFactory(from_=safe_address)
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        another_safe_multisig_transaction = MultisigTransactionFactory()  # Should not appear, it's for another Safe

        # Should not appear unless queued=True, nonce > last mined transaction
        higher_nonce_safe_multisig_transaction = MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        higher_nonce_safe_multisig_transaction_2 = MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)

        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=False&trusted=True')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 4)

        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=True&trusted=True')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 4)

        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=True&trusted=False')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 8)

        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=False&trusted=False')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 6)
        self.assertEqual(len(response.data['results']), 6)
        transfers_not_empty = [False,  # Multisig transaction, no transfer
                               True,  # Erc transfer out
                               True,  # Erc transfer in
                               True,  # internal tx in
                               False,  # Module transaction
                               False,  # Multisig transaction
                               ]
        for transfer_not_empty, transaction in zip(transfers_not_empty, response.data['results']):
            self.assertEqual(bool(transaction['transfers']), transfer_not_empty)
            self.assertTrue(transaction['tx_type'])

        # Test pagination
        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,))
                                   + '?limit=3&queued=False&trusted=False')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 6)
        self.assertEqual(len(response.data['results']), 3)

        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,))
                                   + '?limit=4&offset=4&queued=False&trusted=False')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 6)
        self.assertEqual(len(response.data['results']), 2)

        # Add transfer out for the module transaction and transfer in for the multisig transaction
        erc20_transfer_out = EthereumEventFactory(from_=safe_address,
                                                  ethereum_tx=module_transaction.internal_tx.ethereum_tx)
        # Add token info for that transfer
        token = TokenFactory(address=erc20_transfer_out.address)
        internal_tx_in = InternalTxFactory(to=safe_address, value=8,
                                           ethereum_tx=multisig_transaction.ethereum_tx)
        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=False&trusted=False')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 6)
        self.assertEqual(len(response.data['results']), 6)
        self.assertEqual(response.data['results'][4]['transfers'][0]['token_info'], {
            'type': 'ERC20',
            'address': token.address,
            'name': token.name,
            'symbol': token.symbol,
            'decimals': token.decimals,
            'logo_uri': token.get_full_logo_uri(),
        })
        transfers_not_empty = [False,  # Multisig transaction, no transfer
                               True,  # Erc transfer out
                               True,  # Erc transfer in
                               True,  # internal tx in
                               True,  # Module transaction
                               True,  # Multisig transaction
                               ]
        for transfer_not_empty, transaction in zip(transfers_not_empty, response.data['results']):
            self.assertEqual(bool(transaction['transfers']), transfer_not_empty)

    def test_all_transactions_executed(self):
        safe_address = Account.create().address

        # No mined
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        # Mine tx with higher nonce, all should appear
        MultisigTransactionFactory(safe=safe_address)

        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,))
                                   + '?executed=False&queued=True&trusted=False')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)

        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,))
                                   + '?executed=True&queued=True&trusted=False')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_all_transactions_wrong_transfer_type_view(self):
        # No token in database, so we must trust the event
        safe_address = Account.create().address
        erc20_transfer_out = EthereumEventFactory(from_=safe_address)  # ERC20 event (with `value`)
        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=False&trusted=True')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['transfers'][0]['type'], TransferType.ERC20_TRANSFER.name)
        self.assertIsNone(response.data['results'][0]['transfers'][0]['token_id'])
        self.assertIsNotNone(response.data['results'][0]['transfers'][0]['value'])

        # Result should be the same, as we are adding an ERC20 token
        token = TokenFactory(address=erc20_transfer_out.address, decimals=18)
        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=False&trusted=True')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['transfers'][0]['type'], TransferType.ERC20_TRANSFER.name)
        self.assertIsNone(response.data['results'][0]['transfers'][0]['token_id'])
        self.assertIsNotNone(response.data['results'][0]['transfers'][0]['value'])

        # Result should change if we set the token as an ERC721
        token.decimals = None
        token.save(update_fields=['decimals'])
        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=False&trusted=True')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['transfers'][0]['type'], TransferType.ERC721_TRANSFER.name)
        # TokenId and Value must be swapped now
        self.assertIsNone(response.data['results'][0]['transfers'][0]['value'])
        self.assertIsNotNone(response.data['results'][0]['transfers'][0]['token_id'])

        # It should work with value=0
        safe_address = Account.create().address
        erc20_transfer_out = EthereumEventFactory(from_=safe_address, value=0)  # ERC20 event (with `value`)
        token = TokenFactory(address=erc20_transfer_out.address, decimals=18)
        response = self.client.get(reverse('v1:all-transactions', args=(safe_address,)) + '?queued=False&trusted=True')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['transfers'][0]['type'], TransferType.ERC20_TRANSFER.name)
        self.assertIsNone(response.data['results'][0]['transfers'][0]['token_id'])
        self.assertEqual(response.data['results'][0]['transfers'][0]['value'], '0')

    def test_get_module_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:module-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        module_transaction = ModuleTransactionFactory(safe=safe_address)
        response = self.client.get(reverse('v1:module-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['safe'], module_transaction.safe)
        self.assertEqual(response.data['results'][0]['module'], module_transaction.module)

        # Add another ModuleTransaction to check filters
        ModuleTransactionFactory(safe=safe_address)

        url = reverse('v1:module-transactions',
                      args=(safe_address,)) + f'?transaction_hash={module_transaction.internal_tx.ethereum_tx_id}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

        url = reverse('v1:module-transactions',
                      args=(safe_address,)) + '?transaction_hash=0x2345'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        url = reverse('v1:module-transactions',
                      args=(safe_address,)) + f'?block_number={module_transaction.internal_tx.ethereum_tx.block_id}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_get_multisig_confirmation(self):
        random_safe_tx_hash = Web3.keccak(text='enxebre').hex()
        response = self.client.get(reverse('v1:multisig-transaction-confirmations', args=(random_safe_tx_hash,)),
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        multisig_confirmation_1 = MultisigConfirmationFactory()
        MultisigConfirmationFactory(multisig_transaction=multisig_confirmation_1.multisig_transaction)
        safe_tx_hash = multisig_confirmation_1.multisig_transaction_id
        response = self.client.get(reverse('v1:multisig-transaction-confirmations', args=(safe_tx_hash,)),
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)

    def test_post_multisig_confirmation(self):
        random_safe_tx_hash = Web3.keccak(text='enxebre').hex()
        data = {
            'signature': Account.create().signHash(random_safe_tx_hash)['signature'].hex()  # Not valid signature
        }
        response = self.client.post(reverse('v1:multisig-transaction-confirmations', args=(random_safe_tx_hash,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('was not found', response.data['detail'])

        owner_account_1 = Account.create()
        owner_account_2 = Account.create()
        safe_create2_tx = self.deploy_test_safe(owners=[owner_account_1.address, owner_account_2.address])
        safe_address = safe_create2_tx.safe_address
        multisig_transaction = MultisigTransactionFactory(safe=safe_address, trusted=False)
        safe_tx_hash = multisig_transaction.safe_tx_hash
        response = self.client.post(reverse('v1:multisig-transaction-confirmations', args=(safe_tx_hash,)),
                                    format='json', data={})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        random_account = Account.create()
        data = {
            'signature': random_account.signHash(safe_tx_hash)['signature'].hex()  # Not valid signature
        }
        # Transaction was executed, confirmations cannot be added
        response = self.client.post(reverse('v1:multisig-transaction-confirmations', args=(safe_tx_hash,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f'Transaction with safe-tx-hash={safe_tx_hash} was already executed',
                      response.data['signature'][0])

        # Mark transaction as not executed, signature is still not valid
        multisig_transaction.ethereum_tx = None
        multisig_transaction.save(update_fields=['ethereum_tx'])
        response = self.client.post(reverse('v1:multisig-transaction-confirmations', args=(safe_tx_hash,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f'Signer={random_account.address} is not an owner', response.data['signature'][0])

        data = {
            'signature': owner_account_1.signHash(safe_tx_hash)['signature'].hex()
        }
        self.assertEqual(MultisigConfirmation.objects.count(), 0)
        response = self.client.post(reverse('v1:multisig-transaction-confirmations', args=(safe_tx_hash,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigConfirmation.objects.count(), 1)
        multisig_transaction.refresh_from_db()
        self.assertTrue(multisig_transaction.trusted)

        # Add multiple signatures
        data = {
            'signature': (owner_account_1.signHash(safe_tx_hash)['signature']
                          + owner_account_2.signHash(safe_tx_hash)['signature']).hex()
        }
        self.assertEqual(MultisigConfirmation.objects.count(), 1)
        response = self.client.post(reverse('v1:multisig-transaction-confirmations', args=(safe_tx_hash,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigConfirmation.objects.count(), 2)

    def test_get_multisig_transaction(self):
        safe_tx_hash = Web3.keccak(text='gnosis').hex()
        response = self.client.get(reverse('v1:multisig-transaction', args=(safe_tx_hash,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        add_owner_with_threshold_data = HexBytes('0x0d582f130000000000000000000000001b9a0da11a5cace4e7035993cbb2e4'
                                                 'b1b3b164cf000000000000000000000000000000000000000000000000000000'
                                                 '0000000001')
        multisig_tx = MultisigTransactionFactory(data=add_owner_with_threshold_data)
        safe_tx_hash = multisig_tx.safe_tx_hash
        response = self.client.get(reverse('v1:multisig-transaction', args=(safe_tx_hash,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['confirmations']), 0)
        self.assertTrue(Web3.isChecksumAddress(response.data['executor']))
        self.assertEqual(response.data['transaction_hash'], multisig_tx.ethereum_tx.tx_hash)
        self.assertEqual(response.data['origin'], multisig_tx.origin)
        self.assertEqual(response.data['data_decoded'], {'method': 'addOwnerWithThreshold',
                                                         'parameters': [{'name': 'owner',
                                                                         'type': 'address',
                                                                         'value': '0x1b9a0DA11a5caCE4e703599'
                                                                                  '3Cbb2E4B1B3b164Cf'},
                                                                        {'name': '_threshold',
                                                                         'type': 'uint256',
                                                                         'value': '1'}]
                                                         })
        # Test camelCase
        self.assertEqual(response.json()['transactionHash'], multisig_tx.ethereum_tx.tx_hash)

    def test_get_multisig_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        multisig_tx = MultisigTransactionFactory(safe=safe_address)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['count_unique_nonce'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 0)
        self.assertTrue(Web3.isChecksumAddress(response.data['results'][0]['executor']))
        self.assertEqual(response.data['results'][0]['transaction_hash'], multisig_tx.ethereum_tx.tx_hash)
        # Test camelCase
        self.assertEqual(response.json()['results'][0]['transactionHash'], multisig_tx.ethereum_tx.tx_hash)
        # Check Etag header
        self.assertTrue(response['Etag'])

        MultisigConfirmationFactory(multisig_transaction=multisig_tx)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 1)

        MultisigTransactionFactory(safe=safe_address, nonce=multisig_tx.nonce)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(response.data['count_unique_nonce'], 1)

    def test_get_multisig_transactions_filters(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, nonce=0, ethereum_tx=None)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?nonce=0',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        response = self.client.get(reverse('v1:multisig-transactions',
                                           args=(safe_address,)) + '?to=0x2a',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['to'][0], 'Enter a valid checksummed Ethereum Address.')

        response = self.client.get(reverse('v1:multisig-transactions',
                                           args=(safe_address,)) + f'?to={multisig_transaction.to}',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?nonce=1',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?executed=true',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?executed=false',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        response = self.client.get(reverse('v1:multisig-transactions',
                                           args=(safe_address,)) + '?has_confirmations=True', format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)

        MultisigConfirmationFactory(multisig_transaction=multisig_transaction)
        response = self.client.get(reverse('v1:multisig-transactions',
                                           args=(safe_address,)) + '?has_confirmations=True', format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_post_multisig_transactions(self):
        safe_owner_1 = Account.create()
        safe_create2_tx = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe_create2_tx.safe_address
        safe = Safe(safe_address, self.ethereum_client)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertIsNone(response.data['results'][0]['executor'])
        self.assertEqual(len(response.data['results'][0]['confirmations']), 0)

        # Test confirmation with signature
        data['signature'] = safe_owner_1.signHash(safe_tx.safe_tx_hash)['signature'].hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db.refresh_from_db()
        self.assertTrue(multisig_transaction_db.trusted)  # Now it should be trusted

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(len(response.data['results'][0]['confirmations']), 1)
        self.assertEqual(response.data['results'][0]['confirmations'][0]['signature'], data['signature'])

        # Sign with a different user that sender
        random_user_account = Account.create()
        data['signature'] = random_user_account.signHash(safe_tx.safe_tx_hash)['signature'].hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertIn(f'Signer={random_user_account.address} is not an owner', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Use random user as sender (not owner)
        del data['signature']
        data['sender'] = random_user_account.address
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertIn(f'Sender={random_user_account.address} is not an owner', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_post_executed_transaction(self):
        safe_owner_1 = Account.create()
        safe_create2_tx = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe_create2_tx.safe_address
        safe = Safe(safe_address, self.ethereum_client)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        multisig_transaction = MultisigTransaction.objects.first()
        multisig_transaction.ethereum_tx = EthereumTxFactory()
        multisig_transaction.save(update_fields=['ethereum_tx'])
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(f'Tx with safe-tx-hash={data["contractTransactionHash"]} '
                      f'for safe={safe.address} was already executed in '
                      f'tx-hash={multisig_transaction.ethereum_tx_id}',
                      response.data['non_field_errors'])

        # Check another tx with same nonce
        data['to'] = Account.create().address
        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safeTxGas'], data['baseGas'], data['gasPrice'],
                                         data['gasToken'],
                                         data['refundReceiver'], safe_nonce=data['nonce'])
        data['contractTransactionHash'] = safe_tx.safe_tx_hash.hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(f'Tx with nonce={safe_tx.safe_nonce} for safe={safe.address} '
                      f'already executed in tx-hash={multisig_transaction.ethereum_tx_id}',
                      response.data['non_field_errors'])

        # Successfully insert tx with nonce=1
        data['nonce'] = 1
        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safeTxGas'], data['baseGas'], data['gasPrice'],
                                         data['gasToken'],
                                         data['refundReceiver'], safe_nonce=data['nonce'])
        data['contractTransactionHash'] = safe_tx.safe_tx_hash.hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_post_multisig_transactions_with_origin(self):
        safe_owner_1 = Account.create()
        safe_create2_tx = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe_create2_tx.safe_address
        safe = Safe(safe_address, self.ethereum_client)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        origin_max_len = 200  # Origin field limit
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
                "origin": 'A' * (origin_max_len + 1),
                }

        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safeTxGas'], data['baseGas'], data['gasPrice'],
                                         data['gasToken'],
                                         data['refundReceiver'], safe_nonce=data['nonce'])
        data['contractTransactionHash'] = safe_tx.safe_tx_hash.hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        data['origin'] = 'A' * origin_max_len
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(safe_tx_hash=safe_tx.safe_tx_hash)
        self.assertEqual(multisig_tx_db.origin, data['origin'])

    def test_post_multisig_transactions_with_multiple_signatures(self):
        safe_owners = [Account.create() for _ in range(4)]
        safe_owner_addresses = [s.address for s in safe_owners]
        safe_create2_tx = self.deploy_test_safe(owners=safe_owner_addresses, threshold=3)
        safe_address = safe_create2_tx.safe_address
        safe = Safe(safe_address, self.ethereum_client)

        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

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
                "sender": safe_owners[0].address,
                "origin": 'Testing origin field',
                }

        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safeTxGas'], data['baseGas'], data['gasPrice'],
                                         data['gasToken'],
                                         data['refundReceiver'], safe_nonce=data['nonce'])
        safe_tx_hash = safe_tx.safe_tx_hash
        data['contractTransactionHash'] = safe_tx_hash.hex()
        data['signature'] = b''.join([safe_owner.signHash(safe_tx_hash)['signature']
                                      for safe_owner in safe_owners]).hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(safe_tx_hash=safe_tx.safe_tx_hash)
        self.assertEqual(multisig_tx_db.origin, data['origin'])

        multisig_confirmations = MultisigConfirmation.objects.filter(multisig_transaction_hash=safe_tx_hash)
        self.assertEqual(len(multisig_confirmations), len(safe_owners))
        for multisig_confirmation in multisig_confirmations:
            safe_signatures = SafeSignature.parse_signature(multisig_confirmation.signature, safe_tx_hash)
            self.assertEqual(len(safe_signatures), 1)
            safe_signature = safe_signatures[0]
            self.assertEqual(safe_signature.signature_type, SafeSignatureType.EOA)
            self.assertIn(safe_signature.owner, safe_owner_addresses)
            safe_owner_addresses.remove(safe_signature.owner)

    def test_post_multisig_transactions_with_delegate(self):
        safe_owners = [Account.create() for _ in range(4)]
        safe_owner_addresses = [s.address for s in safe_owners]
        safe_delegate = Account.create()
        safe_create2_tx = self.deploy_test_safe(owners=safe_owner_addresses, threshold=3)
        safe_address = safe_create2_tx.safe_address
        safe = Safe(safe_address, self.ethereum_client)

        self.assertEqual(MultisigTransaction.objects.count(), 0)

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
                "sender": safe_owners[0].address,
                "origin": 'Testing origin field',
                }

        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safeTxGas'], data['baseGas'], data['gasPrice'],
                                         data['gasToken'],
                                         data['refundReceiver'], safe_nonce=data['nonce'])
        safe_tx_hash = safe_tx.safe_tx_hash
        data['contractTransactionHash'] = safe_tx_hash.hex()
        data['signature'] = safe_delegate.signHash(safe_tx_hash)['signature'].hex()

        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(f'Signer={safe_delegate.address} is not an owner or delegate',
                      response.data['non_field_errors'][0])

        data['sender'] = safe_delegate.address
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(f'Sender={safe_delegate.address} is not an owner or delegate',
                      response.data['non_field_errors'][0])

        # Add delegate
        SafeContractDelegateFactory(safe_contract__address=safe_address, delegate=safe_delegate.address)
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigTransaction.objects.count(), 1)
        self.assertEqual(MultisigConfirmation.objects.count(), 0)
        self.assertTrue(MultisigTransaction.objects.first().trusted)

        data['signature'] = data['signature'] + data['signature'][2:]
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn('Just one signature is expected if using delegates', response.data['non_field_errors'][0])

    def test_safe_balances_view(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address, )), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address, )), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIsNone(response.data[0]['token_address'])
        self.assertEqual(response.data[0]['balance'], str(value))

        tokens_value = 12
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        self.assertEqual(Token.objects.count(), 0)
        EthereumEventFactory(address=erc20.address, to=safe_address)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Token.objects.count(), 1)
        self.assertCountEqual(response.json(), [{'tokenAddress': None, 'balance': str(value), 'token': None},
                                                {'tokenAddress': erc20.address, 'balance': str(tokens_value),
                                                 'token': {'name': erc20.functions.name().call(),
                                                           'symbol': erc20.functions.symbol().call(),
                                                           'decimals': erc20.functions.decimals().call(),
                                                           'logoUri': Token.objects.first().get_full_logo_uri()}}])

        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)) + '?trusted=True', format='json')
        self.assertCountEqual(response.json(), [{'tokenAddress': None, 'balance': str(value), 'token': None}])
        Token.objects.all().update(trusted=True)

        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)) + '?trusted=True', format='json')
        self.assertCountEqual(response.json(), [{'tokenAddress': None, 'balance': str(value), 'token': None},
                                                {'tokenAddress': erc20.address, 'balance': str(tokens_value),
                                                 'token': {'name': erc20.functions.name().call(),
                                                           'symbol': erc20.functions.symbol().call(),
                                                           'decimals': erc20.functions.decimals().call(),
                                                           'logoUri': Token.objects.first().get_full_logo_uri()}}])

    @mock.patch.object(BalanceService, 'get_token_info', autospec=True)
    @mock.patch.object(PriceService, 'get_token_eth_value', return_value=0.4, autospec=True)
    @mock.patch.object(PriceService, 'get_eth_usd_price', return_value=123.4, autospec=True)
    @mock.patch.object(timezone, 'now', return_value=timezone.now())
    def test_safe_balances_usd_view(self, timezone_now_mock: MagicMock, get_eth_usd_price_mock: MagicMock,
                                    get_token_eth_value_mock: MagicMock, get_token_info_mock: MagicMock):
        timestamp_str = timezone_now_mock.return_value.isoformat().replace('+00:00', 'Z')
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:safe-balances-usd', args=(safe_address, )), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)
        response = self.client.get(reverse('v1:safe-balances-usd', args=(safe_address, )), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIsNone(response.data[0]['token_address'])
        self.assertEqual(response.data[0]['balance'], str(value))
        self.assertEqual(response.data[0]['eth_value'], '1.0')

        tokens_value = int(12 * 1e18)
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(reverse('v1:safe-balances-usd', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        erc20_info = Erc20InfoWithLogo(erc20.address, 'UXIO', 'UXI', 18, 'http://logo_uri.es')
        get_token_info_mock.return_value = erc20_info

        EthereumEventFactory(address=erc20.address, to=safe_address)
        response = self.client.get(reverse('v1:safe-balances-usd', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token_dict = asdict(erc20_info)
        del token_dict['address']
        self.maxDiff = None
        self.assertCountEqual(response.data, [
            {'token_address': None,
             'token': None,
             'balance': str(value),
             'eth_value': '1.0',
             'timestamp': timestamp_str,
             'fiat_balance': '0.0',
             'fiat_conversion': '123.4',
             'fiat_code': 'USD',
             },  # 7 wei is rounded to 0.0
            {'token_address': erc20.address,
             'token': token_dict,
             'balance': str(tokens_value),
             'eth_value': '0.4',
             'timestamp': timestamp_str,
             'fiat_balance': str(round(123.4 * 0.4 * (tokens_value / 1e18), 4)),
             'fiat_conversion': str(round(123.4 * 0.4, 4)),
             'fiat_code': 'USD',
             }
        ])

    def test_safe_collectibles(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:safe-collectibles', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        response = self.client.get(reverse('v1:safe-collectibles', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

        with mock.patch.object(CollectiblesService, 'get_collectibles_with_metadata', autospec=True) as function:
            token_name = 'TokenName'
            token_symbol = 'SYMBOL'
            token_address = Account.create().address
            logo_uri = f'http://token.org/{token_address}.png'
            token_id = 54
            token_uri = f'http://token.org/token-id/{token_id}'
            image = 'http://token.org/token-id/1/image'
            name = 'Test token name'
            description = 'Test token description'
            function.return_value = [CollectibleWithMetadata(token_name,
                                                             token_symbol,
                                                             logo_uri,
                                                             token_address,
                                                             token_id,
                                                             token_uri,
                                                             {'image': image,
                                                              'name': name,
                                                              'description': description})]
            response = self.client.get(reverse('v1:safe-collectibles', args=(safe_address,)), format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, [{'address': token_address,
                                              'token_name': token_name,
                                              'token_symbol': token_symbol,
                                              'logo_uri': logo_uri,
                                              'id': str(token_id),
                                              'uri': token_uri,
                                              'name': name,
                                              'description': description,
                                              'image_uri': image,
                                              'metadata': {
                                                  'image': image,
                                                  'name': name,
                                                  'description': description,
                                              }}])

    def test_get_safe_delegate_list(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:safe-delegates', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        safe_contract_delegate = SafeContractDelegateFactory()
        safe_address = safe_contract_delegate.safe_contract_id
        response = self.client.get(reverse('v1:safe-delegates', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data['count'], 1)
        result = response.data['results'][0]
        self.assertEqual(result['delegate'], safe_contract_delegate.delegate)
        self.assertEqual(result['delegator'], safe_contract_delegate.delegator)
        self.assertEqual(result['label'], safe_contract_delegate.label)

        safe_contract_delegate = SafeContractDelegateFactory(safe_contract=safe_contract_delegate.safe_contract)
        response = self.client.get(reverse('v1:safe-delegates', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)

        # A different non related Safe should not increase the number
        SafeContractDelegateFactory()
        response = self.client.get(reverse('v1:safe-delegates', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)

    def test_post_safe_delegate(self):
        safe_address = Account.create().address
        delegate_address = Account.create().address
        label = 'Saul Goodman'
        response = self.client.post(reverse('v1:safe-delegates', args=(safe_address, )), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)  # Data is missing

        data = {
            'delegate': delegate_address,
            'label': label,
            'signature': '0x' + '1' * 130,
        }

        owner_account = Account.create()
        safe_address = self.deploy_test_safe(owners=[owner_account.address]).safe_address
        response = self.client.post(reverse('v1:safe-delegates', args=(safe_address, )), format='json', data=data)
        self.assertIn(f'Safe={safe_address} does not exist', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        safe_contract = SafeContractFactory(address=safe_address)
        response = self.client.post(reverse('v1:safe-delegates', args=(safe_address, )), format='json', data=data)
        self.assertIn('Signing owner is not an owner of the Safe', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(SafeContractDelegate.objects.count(), 0)
        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_address)
        data['signature'] = owner_account.signHash(hash_to_sign)['signature'].hex()
        response = self.client.post(reverse('v1:safe-delegates', args=(safe_address, )), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)
        safe_contract_delegate = SafeContractDelegate.objects.first()
        self.assertEqual(safe_contract_delegate.delegate, delegate_address)
        self.assertEqual(safe_contract_delegate.delegator, owner_account.address)
        self.assertEqual(safe_contract_delegate.label, label)

        label = 'Jimmy McGill'
        data['label'] = label
        response = self.client.post(reverse('v1:safe-delegates', args=(safe_address, )), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)
        safe_contract_delegate.refresh_from_db()
        self.assertEqual(safe_contract_delegate.label, label)

        another_label = 'Kim Wexler'
        another_delegate_address = Account.create().address
        data = {
            'delegate': another_delegate_address,
            'label': another_label,
            'signature': owner_account.signHash(DelegateSignatureHelper.calculate_hash(another_delegate_address,
                                                                                       eth_sign=True)
                                                )['signature'].hex(),
        }
        response = self.client.post(reverse('v1:safe-delegates', args=(safe_address, )), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.get(reverse('v1:safe-delegates', args=(safe_address,)), format='json')
        self.assertCountEqual(response.data['results'], [
            {
                'delegate': delegate_address,
                'delegator': owner_account.address,
                'label': label,
            },
            {
                'delegate': another_delegate_address,
                'delegator': owner_account.address,
                'label': another_label,
            },
        ])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)
        self.assertCountEqual(SafeContractDelegate.objects.get_delegates_for_safe(safe_address),
                              [delegate_address, another_delegate_address])

    def test_delete_safe_delegate(self):
        safe_address = Account.create().address
        delegate_address = Account.create().address
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)  # Data is missing

        data = {
            # 'delegate': delegate_address,
            'signature': '0x' + '1' * 130,
        }
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)),
                                      format='json', data=data)
        self.assertIn(f'Safe={safe_address} does not exist', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        owner_account = Account.create()
        safe_address = self.deploy_test_safe(owners=[owner_account.address]).safe_address
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)),
                                      format='json', data=data)
        self.assertIn(f'Safe={safe_address} does not exist', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        safe_contract = SafeContractFactory(address=safe_address)
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)),
                                      format='json', data=data)
        self.assertIn('Signing owner is not an owner of the Safe', response.data['non_field_errors'][0])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Test eth_sign first
        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_address, eth_sign=True)
        data['signature'] = owner_account.signHash(hash_to_sign)['signature'].hex()
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)),
                                      format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Not found', response.data['detail'])

        # Test previous otp
        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_address, previous_topt=True)
        data['signature'] = owner_account.signHash(hash_to_sign)['signature'].hex()
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)),
                                      format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Not found', response.data['detail'])

        hash_to_sign = DelegateSignatureHelper.calculate_hash(delegate_address)
        data['signature'] = owner_account.signHash(hash_to_sign)['signature'].hex()
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)),
                                      format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Not found', response.data['detail'])

        SafeContractDelegateFactory(safe_contract=safe_contract, delegate=delegate_address)
        SafeContractDelegateFactory(safe_contract=safe_contract, delegate=Account.create().address)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)
        response = self.client.delete(reverse('v1:safe-delegate', args=(safe_address, delegate_address)),
                                      format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)

    def test_incoming_transfers_view(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:incoming-transfers', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(len(response.data['results']), 0)

        value = 2
        InternalTxFactory(to=safe_address, value=0)
        internal_tx = InternalTxFactory(to=safe_address, value=value)
        InternalTxFactory(to=Account.create().address, value=value)
        response = self.client.get(reverse('v1:incoming-transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['value'], str(value))
        # Check Etag header
        self.assertTrue(response['Etag'])

        # Test filters
        block_number = internal_tx.ethereum_tx.block_id
        url = reverse('v1:incoming-transfers', args=(safe_address,)) + f'?block_number__gt={block_number}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        # Add from tx. Result should be the same
        InternalTxFactory(_from=safe_address, value=value)
        response = self.client.get(reverse('v1:incoming-transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['value'], str(value))

        url = reverse('v1:incoming-transfers', args=(safe_address,)) + f'?block_number__gt={block_number - 1}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        token_value = 6
        ethereum_erc_20_event = EthereumEventFactory(to=safe_address, value=token_value)
        token = TokenFactory(address=ethereum_erc_20_event.address)
        response = self.client.get(reverse('v1:incoming-transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(response.json()['results'], [
            {'type': TransferType.ERC20_TRANSFER.name,
             'executionDate': ethereum_erc_20_event.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'transactionHash': ethereum_erc_20_event.ethereum_tx_id,
             'blockNumber': ethereum_erc_20_event.ethereum_tx.block_id,
             'to': safe_address,
             'value': str(token_value),
             'tokenId': None,
             'tokenAddress': ethereum_erc_20_event.address,
             'from': ethereum_erc_20_event.arguments['from'],
             'tokenInfo': {
                 'type': 'ERC20',
                 'address': token.address,
                 'name': token.name,
                 'symbol': token.symbol,
                 'decimals': token.decimals,
                 'logoUri': token.get_full_logo_uri(),
             },
             },
            {'type': TransferType.ETHER_TRANSFER.name,
             'executionDate': internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'transactionHash': internal_tx.ethereum_tx_id,
             'blockNumber': internal_tx.ethereum_tx.block_id,
             'to': safe_address,
             'value': str(value),
             'tokenId': None,
             'tokenAddress': None,
             'from': internal_tx._from,
             'tokenInfo': None,
             },
        ])

        token_id = 17
        ethereum_erc_721_event = EthereumEventFactory(to=safe_address, value=token_id, erc721=True)
        response = self.client.get(reverse('v1:incoming-transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(response.json()['results'], [
            {'type': TransferType.ERC721_TRANSFER.name,
             'executionDate': ethereum_erc_721_event.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'transactionHash': ethereum_erc_721_event.ethereum_tx_id,
             'blockNumber': ethereum_erc_721_event.ethereum_tx.block_id,
             'to': safe_address,
             'value': None,
             'tokenId': str(token_id),
             'tokenAddress': ethereum_erc_721_event.address,
             'from': ethereum_erc_721_event.arguments['from'],
             'tokenInfo': None,
             },
            {'type': TransferType.ERC20_TRANSFER.name,
             'executionDate': ethereum_erc_20_event.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'transactionHash': ethereum_erc_20_event.ethereum_tx_id,
             'blockNumber': ethereum_erc_20_event.ethereum_tx.block_id,
             'to': safe_address,
             'value': str(token_value),
             'tokenId': None,
             'tokenAddress': ethereum_erc_20_event.address,
             'from': ethereum_erc_20_event.arguments['from'],
             'tokenInfo': {
                 'type': 'ERC20',
                 'address': token.address,
                 'name': token.name,
                 'symbol': token.symbol,
                 'decimals': token.decimals,
                 'logoUri': token.get_full_logo_uri(),
             },
             },
            {'type': TransferType.ETHER_TRANSFER.name,
             'executionDate': internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'transactionHash': internal_tx.ethereum_tx_id,
             'blockNumber': internal_tx.ethereum_tx.block_id,
             'to': safe_address,
             'value': str(value),
             'tokenId': None,
             'tokenAddress': None,
             'from': internal_tx._from,
             'tokenInfo': None,
             },
        ])

    def test_transfers_view(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:transfers', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(len(response.data['results']), 0)

        value = 2
        InternalTxFactory(to=safe_address, value=0)
        internal_tx = InternalTxFactory(to=safe_address, value=value)
        InternalTxFactory(to=Account.create().address, value=value)
        response = self.client.get(reverse('v1:incoming-transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['value'], str(value))
        # Check Etag header
        self.assertTrue(response['Etag'])

        # Test filters
        block_number = internal_tx.ethereum_tx.block_id
        url = reverse('v1:transfers', args=(safe_address,)) + f'?block_number__gt={block_number}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        url = reverse('v1:transfers', args=(safe_address,)) + f'?block_number__gt={block_number - 1}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

        url = reverse('v1:transfers', args=(safe_address,)) + f'?transaction_hash={internal_tx.ethereum_tx_id}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

        url = reverse('v1:transfers', args=(safe_address,)) + '?transaction_hash=0x2345'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        # Add from tx
        internal_tx_2 = InternalTxFactory(_from=safe_address, value=value)
        response = self.client.get(reverse('v1:transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(response.data['results'][0]['value'], str(value))
        self.assertEqual(response.data['results'][1]['value'], str(value))

        token_value = 6
        ethereum_erc_20_event = EthereumEventFactory(to=safe_address, value=token_value)
        ethereum_erc_20_event_2 = EthereumEventFactory(from_=safe_address, value=token_value)
        token = TokenFactory(address=ethereum_erc_20_event.address)
        response = self.client.get(reverse('v1:transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 4)
        expected_results = [
            {'type': TransferType.ERC20_TRANSFER.name,
             'executionDate': ethereum_erc_20_event_2.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'blockNumber': ethereum_erc_20_event_2.ethereum_tx.block_id,
             'transactionHash': ethereum_erc_20_event_2.ethereum_tx_id,
             'to': ethereum_erc_20_event_2.arguments['to'],
             'value': str(token_value),
             'tokenId': None,
             'tokenAddress': ethereum_erc_20_event_2.address,
             'from': safe_address,
             'tokenInfo': None,
             },
            {'type': TransferType.ERC20_TRANSFER.name,
             'executionDate': ethereum_erc_20_event.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'blockNumber': ethereum_erc_20_event.ethereum_tx.block_id,
             'transactionHash': ethereum_erc_20_event.ethereum_tx_id,
             'to': safe_address,
             'value': str(token_value),
             'tokenId': None,
             'tokenAddress': ethereum_erc_20_event.address,
             'from': ethereum_erc_20_event.arguments['from'],
             'tokenInfo': {
                 'type': 'ERC20',
                 'address': token.address,
                 'name': token.name,
                 'symbol': token.symbol,
                 'decimals': token.decimals,
                 'logoUri': token.get_full_logo_uri(),
             },
             },
            {'type': TransferType.ETHER_TRANSFER.name,
             'executionDate': internal_tx_2.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'blockNumber': internal_tx_2.ethereum_tx.block_id,
             'transactionHash': internal_tx_2.ethereum_tx_id,
             'to': internal_tx_2.to,
             'value': str(value),
             'tokenId': None,
             'tokenAddress': None,
             'from': safe_address,
             'tokenInfo': None,
             },
            {'type': TransferType.ETHER_TRANSFER.name,
             'executionDate': internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'blockNumber': internal_tx.ethereum_tx.block_id,
             'transactionHash': internal_tx.ethereum_tx_id,
             'to': safe_address,
             'value': str(value),
             'tokenId': None,
             'tokenAddress': None,
             'from': internal_tx._from,
             'tokenInfo': None,
             },
        ]
        self.assertEqual(response.json()['results'], expected_results)

        token_id = 17
        ethereum_erc_721_event = EthereumEventFactory(to=safe_address, value=token_id, erc721=True)
        ethereum_erc_721_event_2 = EthereumEventFactory(from_=safe_address, value=token_id, erc721=True)
        response = self.client.get(reverse('v1:transfers', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 6)
        expected_results = [{
            'type': TransferType.ERC721_TRANSFER.name,
            'executionDate': ethereum_erc_721_event_2.ethereum_tx.block.timestamp.isoformat(
            ).replace('+00:00', 'Z'),
            'transactionHash': ethereum_erc_721_event_2.ethereum_tx_id,
            'blockNumber': ethereum_erc_721_event_2.ethereum_tx.block_id,
            'to': ethereum_erc_721_event_2.arguments['to'],
            'value': None,
            'tokenId': str(token_id),
            'tokenAddress': ethereum_erc_721_event_2.address,
            'from': safe_address,
            'tokenInfo': None,
        }, {
            'type': TransferType.ERC721_TRANSFER.name,
            'executionDate': ethereum_erc_721_event.ethereum_tx.block.timestamp.isoformat(
            ).replace('+00:00', 'Z'),
            'transactionHash': ethereum_erc_721_event.ethereum_tx_id,
            'blockNumber': ethereum_erc_721_event.ethereum_tx.block_id,
            'to': safe_address,
            'value': None,
            'tokenId': str(token_id),
            'tokenAddress': ethereum_erc_721_event.address,
            'from': ethereum_erc_721_event.arguments['from'],
            'tokenInfo': None,
        }] + expected_results
        self.assertEqual(response.json()['results'], expected_results)

    def test_safe_creation_view(self):
        invalid_address = '0x2A'
        response = self.client.get(reverse('v1:safe-creation', args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        owner_address = Account.create().address
        response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        with mock.patch.object(ParityManager, 'trace_transaction', autospec=True, return_value=[]):
            # Insert create contract internal tx
            internal_tx = InternalTxFactory(contract_address=owner_address, trace_address='0,0', ethereum_tx__status=1)
            response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)), format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            created_iso = internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z')
            expected = {'created': created_iso,
                        'creator': internal_tx._from,
                        'factory_address': internal_tx._from,
                        'master_copy': None,
                        'setup_data': None,
                        'data_decoded': None,
                        'transaction_hash': internal_tx.ethereum_tx_id}
            self.assertEqual(response.data, expected)

        # Next children internal_tx should not alter the result
        another_trace = dict(call_trace)
        another_trace['traceAddress'] = [0, 0, 0]
        with mock.patch.object(ParityManager, 'trace_transaction', autospec=True, return_value=[another_trace]):
            response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)), format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, expected)

        another_trace_2 = dict(call_trace)
        another_trace_2['traceAddress'] = [0]
        with mock.patch.object(ParityManager, 'trace_transaction', autospec=True, return_value=[another_trace,
                                                                                                another_trace_2]):
            # `another_trace_2` should change the `creator` and `master_copy` and `setup_data` should appear
            # Taken from rinkeby
            create_test_data = {
                'master_copy': '0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A',
                'setup_data': '0xa97ab18a00000000000000000000000000000000000000000000000000000000000000e000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000030000000000000000000000006e45d69a383ceca3d54688e833bd0e1388747e6b00000000000000000000000061a0c717d18232711bc788f19c9cd56a43cc88720000000000000000000000007724b234c9099c205f03b458944942bceba134080000000000000000000000000000000000000000000000000000000000000000',
                'data': '0x61b69abd000000000000000000000000b6029ea3b2c51d09a50b53ca8012feeb05bda35a00000000000000000000000000000000000000000000000000000000000000400000000000000000000000000000000000000000000000000000000000000184a97ab18a00000000000000000000000000000000000000000000000000000000000000e000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000030000000000000000000000006e45d69a383ceca3d54688e833bd0e1388747e6b00000000000000000000000061a0c717d18232711bc788f19c9cd56a43cc88720000000000000000000000007724b234c9099c205f03b458944942bceba13408000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000',
            }
            data_decoded_1 = {'method': 'setup', 'parameters': [{'name': '_owners', 'type': 'address[]', 'value': ['0x6E45d69a383CECa3d54688e833Bd0e1388747e6B', '0x61a0c717d18232711bC788F19C9Cd56a43cc8872', '0x7724b234c9099C205F03b458944942bcEBA13408']}, {'name': '_threshold', 'type': 'uint256', 'value': '1'}, {'name': 'to', 'type': 'address', 'value': '0x0000000000000000000000000000000000000000'}, {'name': 'data', 'type': 'bytes', 'value': '0x'}, {'name': 'paymentToken', 'type': 'address', 'value': '0x0000000000000000000000000000000000000000'}, {'name': 'payment', 'type': 'uint256', 'value': '0'}, {'name': 'paymentReceiver', 'type': 'address', 'value': '0x0000000000000000000000000000000000000000'}]}

            create_test_data_2 = {
                'master_copy': '0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
                'setup_data': '0xb63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000180000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ac9b6dd409ff10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300000000000000000000000085c26101f353f38e45c72d414b44972831f07be3000000000000000000000000235518798770d7336c5c4908dd1019457fea43a10000000000000000000000007f63c25665ea7e85500eaeb806e552e651b07b9d00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000',
                'data': '0x1688f0b900000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f0000000000000000000000000000000000000000000000000000000000000060000000000000000000000000000000000000000000000000000002cecc9e861200000000000000000000000000000000000000000000000000000000000001c4b63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000180000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ac9b6dd409ff10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300000000000000000000000085c26101f353f38e45c72d414b44972831f07be3000000000000000000000000235518798770d7336c5c4908dd1019457fea43a10000000000000000000000007f63c25665ea7e85500eaeb806e552e651b07b9d0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
            }
            data_decoded_2 = {'method': 'setup', 'parameters': [{'name': '_owners', 'type': 'address[]', 'value': ['0x85C26101f353f38E45c72d414b44972831f07BE3', '0x235518798770D7336c5c4908dd1019457FEa43a1', '0x7F63c25665EA7e85500eAEB806E552e651B07b9d']}, {'name': '_threshold', 'type': 'uint256', 'value': '1'}, {'name': 'to', 'type': 'address', 'value': '0x0000000000000000000000000000000000000000'}, {'name': 'data', 'type': 'bytes', 'value': '0x'}, {'name': 'fallbackHandler', 'type': 'address', 'value': '0xd5D82B6aDDc9027B22dCA772Aa68D5d74cdBdF44'}, {'name': 'paymentToken', 'type': 'address', 'value': '0x0000000000000000000000000000000000000000'}, {'name': 'payment', 'type': 'uint256', 'value': '3036537000337393'}, {'name': 'paymentReceiver', 'type': 'address', 'value': '0x0000000000000000000000000000000000000000'}]}

            create_cpk_test_data = {
                'master_copy': '0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
                'setup_data': '0x5714713d000000000000000000000000ff54516a7bc1c1ea952a688e72d5b93a80620074',
                'data': '0x460868ca00000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5fcfe33a586323e7325be6aa6ecd8b4600d232a9037e83c8ece69413b777dabe6500000000000000000000000040a930851bd2e590bd5a5c981b436de25742e9800000000000000000000000005ef44de4b98f2bce0e29c344e7b2fb8f0282a0cf000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000e0000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000245714713d000000000000000000000000ff54516a7bc1c1ea952a688e72d5b93a8062007400000000000000000000000000000000000000000000000000000000',
            }
            data_decoded_cpk = None

            for test_data, data_decoded in [(create_test_data, data_decoded_1),
                                            (create_test_data_2, data_decoded_2),
                                            (create_cpk_test_data, data_decoded_cpk)]:
                another_trace_2['action']['input'] = HexBytes(test_data['data'])
                response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)), format='json')
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                created_iso = internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z')
                self.assertEqual(response.data, {'created': created_iso,
                                                 'creator': another_trace_2['action']['from'],
                                                 'factory_address': internal_tx._from,
                                                 'master_copy': test_data['master_copy'],
                                                 'setup_data': test_data['setup_data'],
                                                 'data_decoded': data_decoded,
                                                 'transaction_hash': internal_tx.ethereum_tx_id})

    def test_safe_info_view(self):
        invalid_address = '0x2A'
        response = self.client.get(reverse('v1:safe-info', args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        safe_create_tx = self.deploy_test_safe()
        safe_address = safe_create_tx.safe_address
        response = self.client.get(reverse('v1:safe-info', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        response = self.client.get(reverse('v1:safe-info', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {
            'address': safe_address,
            'nonce': 0,
            'threshold': safe_create_tx.threshold,
            'owners': safe_create_tx.owners,
            'master_copy': safe_create_tx.master_copy_address,
            'modules': [],
            'fallback_handler': safe_create_tx.fallback_handler,
            'version': '1.1.1'})

        with mock.patch.object(SafeService, 'get_safe_info', side_effect=NodeConnectionError, autospec=True):
            response = self.client.get(reverse('v1:safe-info', args=(safe_address,)), format='json')
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_master_copies_view(self):
        response = self.client.get(reverse('v1:master-copies'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = []
        self.assertEqual(response.data, expected)

        deployed_block_number = 2
        last_indexed_block_number = 5
        safe_master_copy = SafeMasterCopyFactory(initial_block_number=deployed_block_number,
                                                 tx_block_number=last_indexed_block_number)
        response = self.client.get(reverse('v1:master-copies'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {'address': safe_master_copy.address,
             'version': safe_master_copy.version,
             'deployed_block_number': deployed_block_number,
             'last_indexed_block_number': last_indexed_block_number
             }
        ]
        self.assertCountEqual(response.data, expected)

        safe_master_copy = SafeMasterCopyFactory()
        response = self.client.get(reverse('v1:master-copies'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected += [
            {'address': safe_master_copy.address,
             'version': safe_master_copy.version,
             'deployed_block_number': 0,
             'last_indexed_block_number': 0,
             }
        ]

        self.assertCountEqual(response.data, expected)

    def test_analytics_multisig_txs_by_origin_view(self):
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-origin'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        origin = 'Millennium Falcon Navigation Computer'
        origin_2 = 'HAL 9000'
        multisig_transaction = MultisigTransactionFactory(origin=origin)
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-origin'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {'origin': origin, 'transactions': 1},
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin_2)

        response = self.client.get(reverse('v1:analytics-multisig-txs-by-origin'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {'origin': origin_2, 'transactions': 3},
            {'origin': origin, 'transactions': 1},
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin)

        # Check sorting by the biggest
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-origin'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {'origin': origin, 'transactions': 4},
            {'origin': origin_2, 'transactions': 3},
        ]
        self.assertEqual(response.data, expected)

        # Test filters
        origin_3 = 'Skynet'
        safe_address = Account.create().address
        MultisigTransactionFactory(origin=origin_3, safe=safe_address)
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-origin') + f'?safe={safe_address}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {'origin': origin_3, 'transactions': 1},
        ]
        self.assertEqual(response.data, expected)

        response = self.client.get(reverse('v1:analytics-multisig-txs-by-origin') + f'?to={multisig_transaction.to}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {'origin': multisig_transaction.origin, 'transactions': 1},
        ]
        self.assertEqual(response.data, expected)

    def test_analytics_multisig_txs_by_safe_view(self):
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-safe'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_address_1 = Account.create().address
        safe_address_2 = Account.create().address
        safe_address_3 = Account.create().address
        MultisigTransactionFactory(safe=safe_address_1)
        MultisigTransactionFactory(safe=safe_address_1)
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-safe'))
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['results'][0], {'safe': safe_address_1, 'masterCopy': None, 'transactions': 2})
        MultisigTransactionFactory(safe=safe_address_1)
        safe_status_1 = SafeStatusFactory(address=safe_address_1)
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-safe'))
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result['count'], 1)
        self.assertIsNotNone(safe_status_1.master_copy)
        self.assertEqual(result['results'][0], {'safe': safe_address_1,
                                                'masterCopy': safe_status_1.master_copy,
                                                'transactions': 3})
        MultisigTransactionFactory(safe=safe_address_2)
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-safe'))
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result['results'], [
            {'safe': safe_address_1, 'masterCopy': safe_status_1.master_copy, 'transactions': 3},
            {'safe': safe_address_2, 'masterCopy': None, 'transactions': 1}
        ])
        safe_status_2 = SafeStatusFactory(address=safe_address_2)
        safe_status_3 = SafeStatusFactory(address=safe_address_3)
        [MultisigTransactionFactory(safe=safe_address_3) for _ in range(4)]
        response = self.client.get(reverse('v1:analytics-multisig-txs-by-safe'))
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result['results'], [
            {'safe': safe_address_3, 'masterCopy': safe_status_3.master_copy, 'transactions': 4},
            {'safe': safe_address_1, 'masterCopy': safe_status_1.master_copy, 'transactions': 3},
            {'safe': safe_address_2, 'masterCopy': safe_status_2.master_copy, 'transactions': 1}
        ])

        response = self.client.get(reverse('v1:analytics-multisig-txs-by-safe')
                                   + f'?master_copy={safe_status_1.master_copy}')
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result['results'], [
            {'safe': safe_address_1, 'masterCopy': safe_status_1.master_copy, 'transactions': 3},
        ])

    def test_owners_view(self):
        invalid_address = '0x2A'
        response = self.client.get(reverse('v1:owners', args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        owner_address = Account.create().address
        response = self.client.get(reverse('v1:owners', args=(owner_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['safes'], [])

        safe_status = SafeStatusFactory(owners=[owner_address])
        response = self.client.get(reverse('v1:owners', args=(owner_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['safes'], [safe_status.address])

        safe_status_2 = SafeStatusFactory(owners=[owner_address])
        SafeStatusFactory()  # Test that other SafeStatus don't appear
        response = self.client.get(reverse('v1:owners', args=(owner_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data['safes'], [safe_status.address, safe_status_2.address])

    def test_data_decoder_view(self):
        response = self.client.post(reverse('v1:data-decoder'), format='json', data={'data': '0x12'})
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        response = self.client.post(reverse('v1:data-decoder'), format='json', data={'data': '0x12121212'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        add_owner_with_threshold_data = HexBytes('0x0d582f130000000000000000000000001b9a0da11a5cace4e7035993cbb2e4'
                                                 'b1b3b164cf000000000000000000000000000000000000000000000000000000'
                                                 '0000000001')
        response = self.client.post(reverse('v1:data-decoder'), format='json',
                                    data={'data': add_owner_with_threshold_data.hex()})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch.object(Safe, 'estimate_tx_gas', return_value=52000, autospec=True)
    def test_estimate_multisig_tx_view(self, estimate_tx_gas_mock: MagicMock):
        safe_address = Account.create().address
        to = Account.create().address
        data = {"to": to,
                "value": 100000000000000000,
                "data": None,
                "operation": 0,
                }
        response = self.client.post(reverse('v1:multisig-transaction-estimate', args=(safe_address,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        response = self.client.post(reverse('v1:multisig-transaction-estimate', args=(safe_address,)),
                                    format='json', data={})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(reverse('v1:multisig-transaction-estimate', args=(safe_address,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'safe_tx_gas': str(estimate_tx_gas_mock.return_value)})

        estimate_tx_gas_mock.side_effect = CannotEstimateGas
        response = self.client.post(reverse('v1:multisig-transaction-estimate', args=(safe_address,)),
                                    format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
