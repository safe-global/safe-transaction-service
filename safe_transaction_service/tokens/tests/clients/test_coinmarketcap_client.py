import os
import unittest

from django.test import TestCase

from safe_eth.eth.utils import fast_is_checksum_address

from ...clients import CoinMarketCapClient


class TestCoinMarketCapClient(TestCase):
    def test_coinmarketcap_client(self):
        api_token = os.environ.get("COINMARKETCAP_API_TOKEN")
        if not api_token:
            unittest.skip(
                "`COINMARKETCAP_API_TOKEN` environment variable not set, skipping integration test"
            )
        else:
            coinmarketcap_client = CoinMarketCapClient(api_token)
            tokens = coinmarketcap_client.get_ethereum_tokens()
            self.assertGreater(len(tokens), 100)
            for token in tokens:
                self.assertTrue(fast_is_checksum_address(token.token_address))
