from django.test import TestCase

from gnosis.eth import EthereumNetwork

from ...clients import CannotGetPrice
from ...clients.coingecko_client import CoingeckoClient


class TestCoingeckoClient(TestCase):
    GNO_TOKEN_ADDRESS = "0x6810e776880C02933D47DB1b9fc05908e5386b96"
    GNO_GNOSIS_CHAIN_ADDRESS = "0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb"

    def test_coingecko_client(self):
        self.assertTrue(CoingeckoClient.supports_network(EthereumNetwork.MAINNET))
        self.assertTrue(CoingeckoClient.supports_network(EthereumNetwork.BINANCE))
        self.assertTrue(CoingeckoClient.supports_network(EthereumNetwork.MATIC))
        self.assertTrue(CoingeckoClient.supports_network(EthereumNetwork.XDAI))

        # Test Mainnet
        coingecko_client = CoingeckoClient()
        non_existing_token_address = "0xda2f8b8386302C354a90DB670E40beA3563AF454"
        self.assertGreater(coingecko_client.get_token_price(self.GNO_TOKEN_ADDRESS), 0)
        with self.assertRaises(CannotGetPrice):
            coingecko_client.get_token_price(non_existing_token_address)

        # Test Binance
        bsc_coingecko_client = CoingeckoClient(EthereumNetwork.BINANCE)
        binance_peg_ethereum_address = "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"
        self.assertGreater(
            bsc_coingecko_client.get_token_price(binance_peg_ethereum_address), 0
        )

        # Test Polygon
        polygon_coingecko_client = CoingeckoClient(EthereumNetwork.MATIC)
        bnb_pos_address = "0xb33EaAd8d922B1083446DC23f610c2567fB5180f"
        self.assertGreater(polygon_coingecko_client.get_token_price(bnb_pos_address), 0)

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
        coingecko_client = CoingeckoClient(EthereumNetwork.XDAI)
        self.assertIn(
            "http", coingecko_client.get_token_logo_url(self.GNO_GNOSIS_CHAIN_ADDRESS)
        )
