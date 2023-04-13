from unittest import mock

from django.test import TestCase

from requests import Session

from gnosis.eth.tests.utils import just_test_if_mainnet_node

from ...clients import CannotGetPrice, CoingeckoClient, KrakenClient, KucoinClient


class TestClients(TestCase):
    def test_get_bnb_usd_price(self) -> float:
        just_test_if_mainnet_node()
        kucoin_client = KucoinClient()
        coingecko_client = CoingeckoClient()

        price = kucoin_client.get_bnb_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

        price = coingecko_client.get_bnb_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

    def test_get_dai_usd_price_kraken(self) -> float:
        just_test_if_mainnet_node()
        kraken_client = KrakenClient()

        # Kraken is used
        price = kraken_client.get_dai_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

    def test_get_ether_usd_price_kraken(self):
        just_test_if_mainnet_node()
        kraken_client = KrakenClient()

        # Kraken is used
        eth_usd_price = kraken_client.get_ether_usd_price()
        self.assertIsInstance(eth_usd_price, float)
        self.assertGreater(eth_usd_price, 0)

    def test_get_ewt_usd_price_kraken(self) -> float:
        just_test_if_mainnet_node()
        kraken_client = KrakenClient()

        # Kraken is used
        price = kraken_client.get_ewt_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

    def test_get_ether_usd_price_kucoin(self):
        just_test_if_mainnet_node()
        kucoin_client = KucoinClient()

        eth_usd_price = kucoin_client.get_ether_usd_price()
        self.assertIsInstance(eth_usd_price, float)
        self.assertGreater(eth_usd_price, 0)

    def test_get_matic_usd_price(self) -> float:
        just_test_if_mainnet_node()

        for provider in [KucoinClient(), KrakenClient(), CoingeckoClient()]:
            with self.subTest(provider=provider):
                price = provider.get_matic_usd_price()
                self.assertIsInstance(price, float)
                self.assertGreater(price, 0)

    def test_get_ewt_usd_price_coingecko(self) -> float:
        just_test_if_mainnet_node()
        coingecko_client = CoingeckoClient()

        price = coingecko_client.get_ewt_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

    def test_get_ewt_usd_price_kucoin(self) -> float:
        just_test_if_mainnet_node()
        kucoin_client = KucoinClient()

        price = kucoin_client.get_ewt_usd_price()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

        with mock.patch.object(Session, "get", side_effect=IOError("Connection Error")):
            with self.assertRaises(CannotGetPrice):
                kucoin_client.get_ewt_usd_price()
