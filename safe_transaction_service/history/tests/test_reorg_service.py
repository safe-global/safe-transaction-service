from django.test import TestCase

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..services import ReorgServiceProvider


class TestReorgService(EthereumTestCaseMixin, TestCase):
    def test_reorg_service_provider(self):
        ReorgServiceProvider()
