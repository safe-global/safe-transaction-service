from unittest import mock
from unittest.mock import MagicMock

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.transaction import atomic
from django.test import TestCase

from eth_account import Account

from gnosis.eth.clients import (BlockscoutClient, ContractMetadata,
                                EtherscanClient, Sourcify)
from gnosis.eth.ethereum_client import EthereumNetwork
from gnosis.eth.tests.clients.mocks import (etherscan_source_code_mock,
                                            sourcify_safe_metadata)

from ..models import Contract, ContractAbi, validate_abi


class TestContractAbi(TestCase):
    def test_unique_abi(self):
        """
        Abi cannot be unique as it's a very big field
        """
        abi = sourcify_safe_metadata['output']['abi']
        contract_abi = ContractAbi(abi=abi, description='testing')
        contract_abi.full_clean()
        contract_abi.save()

        contract_abi.description = 'testing 2'
        contract_abi.full_clean()
        contract_abi.save()

        contract_abi_2 = ContractAbi(abi=abi, description='whatever')
        with self.assertRaisesMessage(ValidationError, 'Abi cannot be duplicated'):
            contract_abi_2.full_clean()


class TestContract(TestCase):
    @mock.patch.object(Sourcify, '_do_request', autospec=True, return_value=sourcify_safe_metadata)
    @mock.patch.object(EtherscanClient, '_do_request', autospec=True, return_value=etherscan_source_code_mock)
    def test_contract_create_from_address(self, etherscan_request_mock: MagicMock, sourcify_request_mock: MagicMock):
        safe_contract_address = '0x6851D6fDFAfD08c0295C392436245E5bc78B0185'
        network = EthereumNetwork.MAINNET
        contract = Contract.objects.create_from_address(safe_contract_address, network=network)
        self.assertEqual(contract.name, 'GnosisSafe')
        self.assertTrue(contract.contract_abi.abi)
        self.assertEqual(len(contract.contract_abi.abi_functions()), 31)

        with self.assertRaises(IntegrityError):
            with atomic():
                Contract.objects.create_from_address(safe_contract_address, network=network)

        sourcify_request_mock.return_value = None

        # Use etherscan API
        with self.assertRaises(IntegrityError):
            with atomic():
                Contract.objects.create_from_address(safe_contract_address, network=network)

        contract.delete()
        contract = Contract.objects.create_from_address(safe_contract_address, network=network)
        self.assertEqual(contract.name, 'GnosisSafe')
        self.assertTrue(contract.contract_abi.abi)
        self.assertEqual(len(contract.contract_abi.abi_functions()), 31)

        etherscan_request_mock.return_value = None
        new_safe_contract_address = Account.create().address
        contract_without_metadata = Contract.objects.create_from_address(new_safe_contract_address, network=network)
        self.assertEqual(contract_without_metadata.name, '')
        self.assertIsNone(contract_without_metadata.contract_abi)

    def test_validate_abi(self):
        with self.assertRaises(ValidationError):
            validate_abi([])

        with self.assertRaises(ValidationError):
            validate_abi([1])

        with self.assertRaises(ValidationError):
            validate_abi(['a'])

        validate_abi(sourcify_safe_metadata['output']['abi'])

    @mock.patch.object(EtherscanClient, 'get_contract_metadata', autospec=True)
    @mock.patch.object(BlockscoutClient, 'get_contract_metadata', autospec=True, side_effect=IOError)
    @mock.patch.object(Sourcify, 'get_contract_metadata', autospec=True)
    def test_sync_abi_from_api(self,
                               sourcify_get_contract_metadata_mock: MagicMock,
                               blockscout_client_mock: MagicMock,
                               etherscan_get_contract_abi_mock: MagicMock):
        etherscan_get_contract_abi_mock.return_value = ContractMetadata(
            'Etherscan Uxio Contract', [{'anonymous': False,
                                         'inputs': [{'indexed': False,
                                                     'internalType': 'address',
                                                     'name': 'etherscanParam',
                                                     'type': 'address'}],
                                         'name': 'AddedOwner',
                                         'type': 'event'}], False)
        sourcify_get_contract_metadata_mock.return_value = ContractMetadata(
            'Sourcify Uxio Contract', [{'anonymous': False,
                                        'inputs': [{'indexed': False,
                                                    'internalType': 'address',
                                                    'name': 'sourcifyParam',
                                                    'type': 'address'}],
                                        'name': 'AddedOwner',
                                        'type': 'event'}], False)
        contract_name = 'Hello'
        contract = Contract.objects.create(address='0xaE32496491b53841efb51829d6f886387708F99B', name=contract_name,
                                           contract_abi=None)
        network = EthereumNetwork.MAINNET
        self.assertIsNone(contract.contract_abi)
        self.assertEqual(ContractAbi.objects.count(), 0)
        self.assertTrue(contract.sync_abi_from_api(network=network))
        self.assertIsNotNone(contract.contract_abi)
        self.assertEqual(contract.name, contract_name)
        contract_abi = contract.contract_abi
        self.assertEqual(contract_abi.description, sourcify_get_contract_metadata_mock.return_value.name)
        self.assertEqual(contract_abi.abi, sourcify_get_contract_metadata_mock.return_value.abi)
        sourcify_get_contract_metadata_mock.side_effect = IOError  # Now etherscan should be used
        self.assertTrue(contract.sync_abi_from_api(network=network))
        self.assertEqual(ContractAbi.objects.count(), 2)  # A new ABI was inserted
        self.assertNotEqual(contract.contract_abi, contract_abi)  # Contract_abi was changed
        contract_abi.refresh_from_db()
        self.assertEqual(contract_abi.description,
                         sourcify_get_contract_metadata_mock.return_value.name)  # Description should not change

        etherscan_get_contract_abi_mock.side_effect = IOError
        self.assertFalse(contract.sync_abi_from_api(network=network))
