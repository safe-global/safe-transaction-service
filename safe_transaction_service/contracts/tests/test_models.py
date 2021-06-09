from unittest import mock
from unittest.mock import MagicMock

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.transaction import atomic
from django.test import TestCase

from gnosis.eth.clients import Sourcify
from gnosis.eth.clients.sourcify import ContractMetadata
from gnosis.eth.ethereum_client import EthereumNetwork

from ..clients import EtherscanClient
from ..models import Contract, ContractAbi, validate_abi
from .mocks import sourcify_safe_metadata


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
    @mock.patch.object(EtherscanClient, 'get_contract_abi', autospec=True,
                       return_value=sourcify_safe_metadata['output']['abi'])
    def test_contract_create_from_address(self, get_contract_abi_mock: MagicMock, do_request_mock: MagicMock):
        safe_contract_address = '0x6851D6fDFAfD08c0295C392436245E5bc78B0185'
        contract = Contract.objects.create_from_address(safe_contract_address)
        self.assertEqual(contract.name, 'GnosisSafe')
        self.assertTrue(contract.contract_abi.abi)
        self.assertEqual(len(contract.contract_abi.abi_functions()), 31)

        with self.assertRaises(IntegrityError):
            with atomic():
                Contract.objects.create_from_address(safe_contract_address)

        do_request_mock.return_value = None
        # Use etherscan API
        with self.assertRaises(IntegrityError):
            with atomic():
                Contract.objects.create_from_address(safe_contract_address)

        contract.delete()
        contract = Contract.objects.create_from_address(safe_contract_address)
        self.assertEqual(contract.name, '')
        self.assertTrue(contract.contract_abi.abi)
        self.assertEqual(len(contract.contract_abi.abi_functions()), 31)

        get_contract_abi_mock.return_value = None
        self.assertIsNone(Contract.objects.create_from_address(safe_contract_address))

    def test_validate_abi(self):
        with self.assertRaises(ValidationError):
            validate_abi([])

        with self.assertRaises(ValidationError):
            validate_abi([1])

        with self.assertRaises(ValidationError):
            validate_abi(['a'])

        validate_abi(sourcify_safe_metadata['output']['abi'])

    @mock.patch.object(EtherscanClient, 'get_contract_abi', autospec=True,
                       return_value=sourcify_safe_metadata['output']['abi'])
    @mock.patch.object(Sourcify, 'get_contract_metadata', autospec=True,
                       return_value=ContractMetadata('Uxio Contract', [{'anonymous': False,
                                                                        'inputs': [{'indexed': False,
                                                                                    'internalType': 'address',
                                                                                    'name': 'owner',
                                                                                    'type': 'address'}],
                                                                        'name': 'AddedOwner',
                                                                        'type': 'event'}], False))
    def test_sync_abi_from_api(self, sourcify_get_contract_metadata_mock: MagicMock,
                               etherscan_get_contract_abi_mock: MagicMock):
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
        self.assertNotEqual(sourcify_get_contract_metadata_mock.return_value.abi,
                            etherscan_get_contract_abi_mock.return_value)
        sourcify_get_contract_metadata_mock.side_effect = IOError  # Now etherscan should be used
        self.assertTrue(contract.sync_abi_from_api(network=network))
        self.assertEqual(ContractAbi.objects.count(), 2)  # A new ABI was inserted
        self.assertNotEqual(contract.contract_abi, contract_abi)  # Contract_abi was changed

        etherscan_get_contract_abi_mock.side_effect = IOError
        self.assertFalse(contract.sync_abi_from_api(network=network))
