from django.test import TestCase

from eth_account import Account

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..services.safe_service import (CannotGetSafeInfo, SafeCreationInfo,
                                     SafeInfo, SafeServiceProvider)
from .factories import InternalTxFactory


class TestSafeService(SafeTestCaseMixin, TestCase):
    def setUp(self) -> None:
        self.safe_service = SafeServiceProvider()

    def test_get_safe_creation_info(self):
        random_address = Account.create().address
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        InternalTxFactory(contract_address=random_address, ethereum_tx__status=0)
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        InternalTxFactory(contract_address=random_address, ethereum_tx__status=1)
        safe_creation_info = self.safe_service.get_safe_creation_info(random_address)
        self.assertIsInstance(safe_creation_info, SafeCreationInfo)

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
