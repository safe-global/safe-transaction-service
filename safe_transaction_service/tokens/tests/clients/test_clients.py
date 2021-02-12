from django.test import TestCase

from gnosis.eth.tests.utils import just_test_if_mainnet_node

from ...clients import (BinanceClient, CoingeckoClient, KrakenClient,
                        KucoinClient)


class TestClients(TestCase):
    def test_get_dai_usd_price_kraken(self) -> float:
        just_test_if_mainnet_node()
        kraken_client = KrakenClient()

        # Binance is used
        price = kraken_client.get_dai_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

    def test_get_eth_usd_price_kraken(self):
        just_test_if_mainnet_node()
        kraken_client = KrakenClient()

        # Kraken is used
        eth_usd_price = kraken_client.get_eth_usd_price()
        self.assertIsInstance(eth_usd_price, float)
        self.assertGreater(eth_usd_price, 0)

    def test_get_eth_usd_price_binance(self):
        just_test_if_mainnet_node()
        binance_client = BinanceClient()

        # Binance is used
        eth_usd_price = binance_client.get_eth_usd_price()
        self.assertIsInstance(eth_usd_price, float)
        self.assertGreater(eth_usd_price, 0)

    def test_get_ewt_usd_price_coingecko(self) -> float:
        just_test_if_mainnet_node()
        coingecko_client = CoingeckoClient()

        price = coingecko_client.get_ewt_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

    def test_get_ewt_usd_price_kucoin(self) -> float:
        just_test_if_mainnet_node()
        balance_service = KucoinClient()

        price = balance_service.get_ewt_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)
