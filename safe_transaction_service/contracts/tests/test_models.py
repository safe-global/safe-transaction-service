from typing import List
from unittest import mock
from unittest.mock import MagicMock

from django.db import IntegrityError
from django.test import TestCase

from .mocks import sourcify_safe_metadata
from ..models import Contract
from ..sourcify import Sourcify


class TestContract(TestCase):
    @mock.patch.object(Sourcify, '_do_request', autospec=True, return_value=sourcify_safe_metadata)
    def test_contract_create_from_address(self, do_request_mock: MagicMock):
        safe_contract_address = '0x6851D6fDFAfD08c0295C392436245E5bc78B0185'
        contract = Contract.objects.create_from_address(safe_contract_address)
        self.assertEqual(contract.name, 'GnosisSafe')
        self.assertTrue(contract.contract_abi.abi)

        with self.assertRaises(IntegrityError):
            Contract.objects.create_from_address(safe_contract_address)

        do_request_mock.return_value = None
        self.assertIsNone(Contract.objects.create_from_address(safe_contract_address))
