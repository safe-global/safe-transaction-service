from django.test import TestCase

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..services import BalanceServiceProvider


class TestBalanceService(EthereumTestCaseMixin, TestCase):
    def test_balance_service_provider(self):
        BalanceServiceProvider()
