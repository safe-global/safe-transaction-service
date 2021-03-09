from unittest import mock
from unittest.mock import MagicMock

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.transaction import atomic
from django.test import TestCase

from gnosis.eth.clients import Sourcify
from gnosis.eth.ethereum_client import EthereumNetwork

from ..clients import EtherscanApi
from ..models import Contract, validate_abi
from .mocks import sourcify_safe_metadata


class TestContract(TestCase):
    @mock.patch.object(Sourcify, '_do_request', autospec=True, return_value=sourcify_safe_metadata)
    @mock.patch.object(EtherscanApi, 'get_contract_abi', autospec=True,
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

    @mock.patch.object(EtherscanApi, 'get_contract_abi', autospec=True,
                       return_value=sourcify_safe_metadata['output']['abi'])
    def test_sync_abi_from_api(self, get_contract_abi_mock: MagicMock):
        contract_name = 'Hello'
        contract = Contract.objects.create(address='0xaE32496491b53841efb51829d6f886387708F99B', name=contract_name,
                                           contract_abi=None)
        network = EthereumNetwork.MAINNET
        self.assertIsNone(contract.contract_abi)
        contract.sync_abi_from_api(network=network)
        self.assertIsNotNone(contract.contract_abi)
        self.assertEqual(contract.name, contract_name)
