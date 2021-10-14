from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClient
from gnosis.eth.oracles import (
    KyberOracle,
    OracleException,
    UniswapOracle,
    UniswapV2Oracle,
)

from safe_transaction_service.history.tests.utils import just_test_if_mainnet_node
from safe_transaction_service.utils.redis import get_redis

from ..clients import (
    BinanceClient,
    CannotGetPrice,
    CoingeckoClient,
    KrakenClient,
    KucoinClient,
)
from ..services.price_service import PriceService, PriceServiceProvider


class TestPriceService(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.price_service = PriceServiceProvider()
        cls.redis = get_redis()

    @classmethod
    def tearDownClass(cls) -> None:
        PriceServiceProvider.del_singleton()

    @mock.patch.object(KrakenClient, "get_eth_usd_price", return_value=0.4)
    @mock.patch.object(BinanceClient, "get_eth_usd_price", return_value=0.5)
    def test_get_eth_usd_price(self, binance_mock: MagicMock, kraken_mock: MagicMock):
        price_service = self.price_service
        eth_usd_price = price_service.get_eth_usd_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)
        binance_mock.assert_not_called()

        kraken_mock.side_effect = CannotGetPrice

        # Cache is still working
        eth_usd_price = price_service.get_eth_usd_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)

        # Remove cache and test binance is called
        price_service.cache_eth_price.clear()
        eth_usd_price = price_service.get_eth_usd_price()
        binance_mock.called_once()
        self.assertEqual(eth_usd_price, binance_mock.return_value)

    @mock.patch.object(CoingeckoClient, "get_ewt_usd_price", return_value=3.0)
    @mock.patch.object(KucoinClient, "get_ewt_usd_price", return_value=7.0)
    @mock.patch.object(KrakenClient, "get_ewt_usd_price", return_value=5.0)
    def test_get_ewt_usd_price(
        self,
        get_ewt_usd_price_kraken_mock: MagicMock,
        get_ewt_usd_price_kucoin_mock: MagicMock,
        get_ewt_usd_price_coingecko_mock: MagicMock,
    ):
        price_service = self.price_service

        price = price_service.get_ewt_usd_price()
        self.assertEqual(price, 5.0)

        get_ewt_usd_price_kraken_mock.side_effect = CannotGetPrice
        price = price_service.get_ewt_usd_price()
        self.assertEqual(price, 7.0)

        get_ewt_usd_price_kucoin_mock.side_effect = CannotGetPrice
        price = price_service.get_ewt_usd_price()
        self.assertEqual(price, 3.0)

    @mock.patch.object(CoingeckoClient, "get_matic_usd_price", return_value=3.0)
    @mock.patch.object(BinanceClient, "get_matic_usd_price", return_value=7.0)
    @mock.patch.object(KrakenClient, "get_matic_usd_price", return_value=5.0)
    def test_get_matic_usd_price(
        self,
        get_matic_usd_price_kraken_mock: MagicMock,
        get_matic_usd_price_binance_mock: MagicMock,
        get_matic_usd_price_coingecko_mock: MagicMock,
    ):
        price_service = self.price_service

        price = price_service.get_matic_usd_price()
        self.assertEqual(price, 5.0)

        get_matic_usd_price_kraken_mock.side_effect = CannotGetPrice
        price = price_service.get_matic_usd_price()
        self.assertEqual(price, 7.0)

        get_matic_usd_price_binance_mock.side_effect = CannotGetPrice
        price = price_service.get_matic_usd_price()
        self.assertEqual(price, 3.0)

    def test_token_eth_value(self):
        mainnet_node = just_test_if_mainnet_node()
        price_service = PriceService(EthereumClient(mainnet_node), self.redis)
        gno_token_address = "0x6810e776880C02933D47DB1b9fc05908e5386b96"
        token_eth_value = price_service.get_token_eth_value(gno_token_address)
        self.assertIsInstance(token_eth_value, float)
        self.assertGreater(token_eth_value, 0)

    @mock.patch.object(KyberOracle, "get_price", return_value=1.23, autospec=True)
    def test_token_eth_value_mocked(self, kyber_get_price_mock: MagicMock):
        price_service = self.price_service
        random_address = Account.create().address
        self.assertEqual(len(price_service.cache_token_eth_value), 0)
        self.assertEqual(price_service.get_token_eth_value(random_address), 1.23)
        self.assertEqual(price_service.cache_token_eth_value[(random_address,)], 1.23)

        # Every oracle is not accesible
        kyber_get_price_mock.side_effect = OracleException
        with mock.patch.object(
            UniswapOracle, "get_price", side_effect=OracleException, autospec=True
        ):
            with mock.patch.object(
                UniswapV2Oracle, "get_price", side_effect=OracleException, autospec=True
            ):
                self.assertEqual(
                    price_service.get_token_eth_value(random_address), 1.23
                )
                random_address_2 = Account.create().address
                self.assertEqual(
                    price_service.get_token_eth_value(random_address_2), 0.0
                )
                self.assertEqual(
                    price_service.cache_token_eth_value[(random_address,)], 1.23
                )
                self.assertEqual(
                    price_service.cache_token_eth_value[(random_address_2,)], 0.0
                )
