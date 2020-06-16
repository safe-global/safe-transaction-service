import unittest

from django.test import TestCase

from ...clients.etherscan_client import EtherscanClient


class TestEtherscanClient(TestCase):
    @unittest.skip('Requires Node installed')
    def test_get_tokens_page(self):
        etherscan_client = EtherscanClient()
        elements = 10
        tokens = etherscan_client.get_tokens_page(elements=elements)
        self.assertEqual(len(tokens), elements)
