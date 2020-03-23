import logging
from unittest import mock

from django.urls import reverse

from eth_account import Account
from hexbytes import HexBytes
from rest_framework import status
from rest_framework.test import APITestCase
from web3 import Web3

from gnosis.eth.ethereum_client import Erc20Info
from gnosis.safe import Safe
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import MultisigTransaction
from ..services import BalanceService
from .factories import (EthereumEventFactory, InternalTxFactory,
                        ModuleTransactionFactory, MultisigConfirmationFactory,
                        MultisigTransactionFactory, SafeContractFactory,
                        SafeStatusFactory)

logger = logging.getLogger(__name__)


class TestViews(SafeTestCaseMixin, APITestCase):
    def test_get_module_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:module-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        module_transaction = ModuleTransactionFactory(safe=safe_address)
        response = self.client.get(reverse('v1:module-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['safe'], module_transaction.safe)
        self.assertEqual(response.data['results'][0]['module'], module_transaction.module)

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
        self.assertEqual(response.data['data_decoded'], {'addOwnerWithThreshold': [{'name': 'owner',
                                                                                    'type': 'address',
                                                                                    'value': '0x1b9a0DA11a5caCE4e703599'
                                                                                             '3Cbb2E4B1B3b164Cf'},
                                                                                   {'name': '_threshold',
                                                                                    'type': 'uint256',
                                                                                    'value': 1}]
                                                         })
        # Test camelCase
        self.assertEqual(response.json()['transactionHash'], multisig_tx.ethereum_tx.tx_hash)

    def test_get_multisig_transactions(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        multisig_transaction = MultisigTransactionFactory(safe=safe_address, nonce=0, ethereum_tx=None)
        response = self.client.get(reverse('v1:multisig-transactions', args=(safe_address,)) + '?nonce=0',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        response = self.client.get(reverse('v1:multisig-transactions',
                                           args=(safe_address,)) + f'?to=0x2a',
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

    def test_post_multisig_transactions_with_origin(self):
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
                "origin": 'Testing origin field',
                }

        safe_tx = safe.build_multisig_tx(data['to'], data['value'], data['data'], data['operation'],
                                         data['safeTxGas'], data['baseGas'], data['gasPrice'],
                                         data['gasToken'],
                                         data['refundReceiver'], safe_nonce=data['nonce'])
        data['contractTransactionHash'] = safe_tx.safe_tx_hash.hex()
        response = self.client.post(reverse('v1:multisig-transactions', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        multisig_tx_db = MultisigTransaction.objects.get(safe_tx_hash=safe_tx.safe_tx_hash)
        self.assertEqual(multisig_tx_db.origin, data['origin'])

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

        EthereumEventFactory(address=erc20.address, to=safe_address)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.json(), [{'tokenAddress': None, 'balance': str(value), 'token': None},
                                                {'tokenAddress': erc20.address, 'balance': str(tokens_value),
                                                 'token': {'name': erc20.functions.name().call(),
                                                           'symbol': erc20.functions.symbol().call(),
                                                           'decimals': erc20.functions.decimals().call()}}])

    @mock.patch.object(BalanceService, 'get_token_info',  autospec=True)
    @mock.patch.object(BalanceService, 'get_token_eth_value', return_value=0.4, autospec=True)
    @mock.patch.object(BalanceService, 'get_eth_usd_price', return_value=123.4, autospec=True)
    def test_safe_balances_usd_view(self, get_eth_usd_price_mock, get_token_eth_value_mock, get_token_info_mock):
        erc20_info = Erc20Info('UXIO', 'UXI', 18)
        get_token_info_mock.return_value = erc20_info

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

        tokens_value = int(12 * 1e18)
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(reverse('v1:safe-balances-usd', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        EthereumEventFactory(address=erc20.address, to=safe_address)
        response = self.client.get(reverse('v1:safe-balances-usd', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.json(), [{'tokenAddress': None, 'token': None, 'balance': str(value),
                                                 'balanceUsd': "0.0"},  # 7 wei is rounded to 0.0
                                                {'tokenAddress': erc20.address,
                                                 'token': erc20_info._asdict(),
                                                 'balance': str(tokens_value),
                                                 'balanceUsd': str(round(123.4 * 0.4 * (tokens_value / 1e18), 4))}])

    def test_incoming_txs_view(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:incoming-transactions', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(len(response.data['results']), 0)

        value = 2
        InternalTxFactory(to=safe_address, value=0)
        internal_tx = InternalTxFactory(to=safe_address, value=value)
        InternalTxFactory(to=Account.create().address, value=value)
        response = self.client.get(reverse('v1:incoming-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['value'], str(value))
        # Check Etag header
        self.assertTrue(response['Etag'])

        # Test filters
        block_number = internal_tx.ethereum_tx.block_id
        url = reverse('v1:incoming-transactions', args=(safe_address,)) + f'?block_number__gt={block_number}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        url = reverse('v1:incoming-transactions', args=(safe_address,)) + f'?block_number__gt={block_number - 1}'
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        token_value = 6
        ethereum_event = EthereumEventFactory(to=safe_address, value=token_value)
        response = self.client.get(reverse('v1:incoming-transactions', args=(safe_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertCountEqual(response.json()['results'], [
            {'executionDate': internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'transactionHash': internal_tx.ethereum_tx_id,
             'blockNumber': internal_tx.ethereum_tx.block_id,
             'to': safe_address,
             'value': str(value),
             'tokenAddress': None,
             'from': internal_tx._from,
             },
            {'executionDate': ethereum_event.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z'),
             'transactionHash': ethereum_event.ethereum_tx_id,
             'blockNumber': ethereum_event.ethereum_tx.block_id,
             'to': safe_address,
             'value': str(token_value),
             'tokenAddress': ethereum_event.address,
             'from': ethereum_event.arguments['from']
             }
        ])

    def test_safe_creation_view(self):
        invalid_address = '0x2A'
        response = self.client.get(reverse('v1:safe-creation', args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        owner_address = Account.create().address
        response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        internal_tx = InternalTxFactory(contract_address=owner_address, trace_address='0,0')
        response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        created_iso = internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z')
        expected = {'created': created_iso,
                    'creator': internal_tx._from,
                    'factory_address': internal_tx._from,
                    'master_copy': None,
                    'setup_data': None,
                    'transaction_hash': internal_tx.ethereum_tx_id}
        self.assertEqual(response.data, expected)

        # Next internal_tx should not alter the result
        next_internal_tx = InternalTxFactory(trace_address='0,0,0', ethereum_tx=internal_tx.ethereum_tx)
        response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, expected)

        # Previous internal_tx should change the `creator` and `master_copy` and `setup_data` should appear
        # Taken from rinkeby
        create_test_data = {
            'master_copy': '0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A',
            'setup_data': '0xa97ab18a00000000000000000000000000000000000000000000000000000000000000e000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000030000000000000000000000006e45d69a383ceca3d54688e833bd0e1388747e6b00000000000000000000000061a0c717d18232711bc788f19c9cd56a43cc88720000000000000000000000007724b234c9099c205f03b458944942bceba134080000000000000000000000000000000000000000000000000000000000000000',
            'data': '0x61b69abd000000000000000000000000b6029ea3b2c51d09a50b53ca8012feeb05bda35a00000000000000000000000000000000000000000000000000000000000000400000000000000000000000000000000000000000000000000000000000000184a97ab18a00000000000000000000000000000000000000000000000000000000000000e000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000016000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000030000000000000000000000006e45d69a383ceca3d54688e833bd0e1388747e6b00000000000000000000000061a0c717d18232711bc788f19c9cd56a43cc88720000000000000000000000007724b234c9099c205f03b458944942bceba13408000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000',
        }
        create_test_data_2 = {
            'master_copy': '0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
            'setup_data': '0xb63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000180000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ac9b6dd409ff10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300000000000000000000000085c26101f353f38e45c72d414b44972831f07be3000000000000000000000000235518798770d7336c5c4908dd1019457fea43a10000000000000000000000007f63c25665ea7e85500eaeb806e552e651b07b9d00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000',
            'data': '0x1688f0b900000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f0000000000000000000000000000000000000000000000000000000000000060000000000000000000000000000000000000000000000000000002cecc9e861200000000000000000000000000000000000000000000000000000000000001c4b63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000180000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ac9b6dd409ff10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300000000000000000000000085c26101f353f38e45c72d414b44972831f07be3000000000000000000000000235518798770d7336c5c4908dd1019457fea43a10000000000000000000000007f63c25665ea7e85500eaeb806e552e651b07b9d0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
        }

        create_cpk_test_data = {
            'master_copy': '0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
            'setup_data': '0x5714713d000000000000000000000000ff54516a7bc1c1ea952a688e72d5b93a80620074',
            'data': '0x460868ca00000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5fcfe33a586323e7325be6aa6ecd8b4600d232a9037e83c8ece69413b777dabe6500000000000000000000000040a930851bd2e590bd5a5c981b436de25742e9800000000000000000000000005ef44de4b98f2bce0e29c344e7b2fb8f0282a0cf000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000e0000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000245714713d000000000000000000000000ff54516a7bc1c1ea952a688e72d5b93a8062007400000000000000000000000000000000000000000000000000000000',
        }

        previous_internal_tx = InternalTxFactory(trace_address='0', ethereum_tx=internal_tx.ethereum_tx)
        for test_data in [create_test_data, create_test_data_2, create_cpk_test_data]:
            previous_internal_tx.data = HexBytes(test_data['data'])
            previous_internal_tx.save(update_fields=['data'])
            response = self.client.get(reverse('v1:safe-creation', args=(owner_address,)), format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            created_iso = internal_tx.ethereum_tx.block.timestamp.isoformat().replace('+00:00', 'Z')
            self.assertEqual(response.data, {'created': created_iso,
                                             'creator': previous_internal_tx._from,
                                             'factory_address': internal_tx._from,
                                             'master_copy': test_data['master_copy'],
                                             'setup_data': test_data['setup_data'],
                                             'transaction_hash': internal_tx.ethereum_tx_id})

    def test_owners_view(self):
        invalid_address = '0x2A'
        response = self.client.get(reverse('v1:owners', args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        owner_address = Account.create().address
        response = self.client.get(reverse('v1:owners', args=(owner_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        safe_status = SafeStatusFactory(owners=[owner_address])
        response = self.client.get(reverse('v1:owners', args=(owner_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data['safes'], [safe_status.address])

        safe_status_2 = SafeStatusFactory(owners=[owner_address])
        SafeStatusFactory()  # Test that other SafeStatus don't appear
        response = self.client.get(reverse('v1:owners', args=(owner_address,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data['safes'], [safe_status.address, safe_status_2.address])
