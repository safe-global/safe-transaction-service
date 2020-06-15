from django.test import TestCase

from ...clients import SafeRelayTokenClient


class TestSafeRelayTokenClient(TestCase):
    def test_safe_relay_token_client(self):
        safe_relay_token_client = SafeRelayTokenClient('https://safe-relay.gnosis.io/')
        self.assertGreater(len(safe_relay_token_client.get_tokens()), 100)
