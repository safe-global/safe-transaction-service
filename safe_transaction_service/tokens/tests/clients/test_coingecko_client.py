from django.test import TestCase

from gnosis.eth import EthereumNetwork

from safe_transaction_service.history.tests.utils import skip_on

from ...clients.coingecko_client import CoingeckoClient
from ...clients.exceptions import CoingeckoRateLimitError


class TestCoingeckoClient(TestCase):
    GNO_TOKEN_ADDRESS = "0x6810e776880C02933D47DB1b9fc05908e5386b96"
    GNO_GNOSIS_CHAIN_ADDRESS = "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb"

    @skip_on(CoingeckoRateLimitError, reason="Coingecko rate limit reached")
    def test_get_logo_url(self):
        # Test Mainnet
        coingecko_client = CoingeckoClient()
        self.assertIn(
            "http", coingecko_client.get_token_logo_url(self.GNO_TOKEN_ADDRESS)
        )
        self.assertIsNone(
            coingecko_client.get_token_logo_url(self.GNO_GNOSIS_CHAIN_ADDRESS)
        )

        # Test Gnosis Chain
        coingecko_client = CoingeckoClient(EthereumNetwork.GNOSIS)
        self.assertIn(
            "http", coingecko_client.get_token_logo_url(self.GNO_GNOSIS_CHAIN_ADDRESS)
        )
