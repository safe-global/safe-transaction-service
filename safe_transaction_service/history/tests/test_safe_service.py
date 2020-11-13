from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account

from gnosis.eth.ethereum_client import ParityManager
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..services.safe_service import (CannotGetSafeInfo, SafeCreationInfo,
                                     SafeInfo, SafeServiceProvider)
from .factories import InternalTxFactory
from .mocks.traces import create_trace, creation_internal_txs


class TestSafeService(SafeTestCaseMixin, TestCase):
    def setUp(self) -> None:
        self.safe_service = SafeServiceProvider()

    def test_get_safe_creation_info(self):
        random_address = Account.create().address
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        InternalTxFactory(contract_address=random_address, ethereum_tx__status=0)
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        with mock.patch.object(ParityManager, 'trace_transaction', autospec=True, return_value=[create_trace]):
            InternalTxFactory(contract_address=random_address, ethereum_tx__status=1, trace_address='0')
            safe_creation_info = self.safe_service.get_safe_creation_info(random_address)
            self.assertIsInstance(safe_creation_info, SafeCreationInfo)

    @mock.patch.object(ParityManager, 'trace_transaction', return_value=creation_internal_txs)
    def test_get_safe_creation_info_with_next_trace(self, trace_transaction_mock: MagicMock):
        random_address = Account.create().address
        InternalTxFactory(contract_address=random_address, ethereum_tx__status=1, trace_address='')
        safe_creation_info = self.safe_service.get_safe_creation_info(random_address)
        self.assertIsInstance(safe_creation_info, SafeCreationInfo)
        self.assertEqual(safe_creation_info.master_copy, '0x8942595A2dC5181Df0465AF0D7be08c8f23C93af')
        self.assertTrue(safe_creation_info.setup_data)
        trace_transaction_mock.return_value = []
        safe_creation_info = self.safe_service.get_safe_creation_info(random_address)
        self.assertIsNone(safe_creation_info.master_copy)
        self.assertIsNone(safe_creation_info.setup_data)

    def test_get_safe_info(self):
        safe_address = Account.create().address
        with self.assertRaises(CannotGetSafeInfo):
            self.safe_service.get_safe_info(safe_address)

        safe_create_tx = self.deploy_test_safe()
        safe_info = self.safe_service.get_safe_info(safe_create_tx.safe_address)
        self.assertIsInstance(safe_info, SafeInfo)
        self.assertEqual(safe_info.address, safe_create_tx.safe_address)
        self.assertEqual(safe_info.owners, safe_create_tx.owners)
        self.assertEqual(safe_info.threshold, safe_create_tx.threshold)
