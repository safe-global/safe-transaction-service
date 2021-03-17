import unittest

from django.test import TestCase

from eth_utils import is_checksum_address

from ...clients import SafeRelayTokenClient


class TestSafeRelayTokenClient(TestCase):
    @unittest.skip('Not needed anymore')
    def test_safe_relay_token_client(self):
        safe_relay_token_client = SafeRelayTokenClient()
        tokens = safe_relay_token_client.get_tokens()
        self.assertGreater(len(tokens), 100)
        for token in tokens:
            self.assertTrue(is_checksum_address(token.address))
            self.assertGreaterEqual(token.decimals, 0)
