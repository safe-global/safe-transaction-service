from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClient, EthereumClientProvider, EthereumNetwork
from gnosis.eth.oracles import KyberOracle, OracleException, UnderlyingToken

from safe_transaction_service.history.tests.utils import just_test_if_mainnet_node
from safe_transaction_service.utils.redis import get_redis

from ..clients import CannotGetPrice, CoingeckoClient, KrakenClient, KucoinClient
from ..services.price_service import PriceService, PriceServiceProvider


class TestPriceService(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.redis = get_redis()
        cls.ethereum_client = EthereumClientProvider()

    @classmethod
    def tearDownClass(cls) -> None:
        PriceServiceProvider.del_singleton()

    def setUp(self) -> None:
        self.price_service = PriceServiceProvider()

    def tearDown(self) -> None:
        PriceServiceProvider.del_singleton()

    def test_available_price_oracles(self):
        # Ganache should have no oracle enabled
        self.assertEqual(len(self.price_service.enabled_price_oracles), 0)
        self.assertEqual(len(self.price_service.enabled_price_pool_oracles), 0)
        self.assertEqual(len(self.price_service.enabled_composed_price_oracles), 0)

    def test_available_price_oracles_mainnet(self):
        # Mainnet should have every oracle enabled
        mainnet_node = just_test_if_mainnet_node()
        price_service = PriceService(EthereumClient(mainnet_node), self.redis)
        self.assertEqual(len(price_service.enabled_price_oracles), 6)
        self.assertEqual(len(price_service.enabled_price_pool_oracles), 3)
        self.assertEqual(len(price_service.enabled_composed_price_oracles), 4)

    @mock.patch.object(KrakenClient, "get_ether_usd_price", return_value=0.4)
    @mock.patch.object(KucoinClient, "get_ether_usd_price", return_value=0.5)
    def test_get_ether_usd_price(self, kucoin_mock: MagicMock, kraken_mock: MagicMock):
        price_service = self.price_service
        eth_usd_price = price_service.get_ether_usd_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)
        kucoin_mock.assert_not_called()

        kraken_mock.side_effect = CannotGetPrice

        # cache_ether_usd_price is working
        eth_usd_price = price_service.get_native_coin_usd_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)

        # Clear cache_ether_usd_price
        price_service.cache_ether_usd_price.clear()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)
        kucoin_mock.assert_not_called()

    def test_get_native_coin_usd_price(self):
        price_service = self.price_service

        # Unsupported network (Ganache)
        with mock.patch.object(
            KrakenClient, "get_ether_usd_price", return_value=1_600
        ) as kraken_mock:
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 1_600)

            # Test cache is working
            kraken_mock.side_effect = CannotGetPrice
            self.assertEqual(price_service.get_native_coin_usd_price(), 1_600)

        # Gnosis Chain
        price_service.ethereum_network = EthereumNetwork.GNOSIS
        with mock.patch.object(KrakenClient, "get_dai_usd_price", return_value=1.5):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 1.5)

        with mock.patch.object(
            KrakenClient, "get_dai_usd_price", side_effect=CannotGetPrice
        ):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 1)

        # POLYGON
        price_service.ethereum_network = EthereumNetwork.POLYGON
        with mock.patch.object(KrakenClient, "get_matic_usd_price", return_value=0.7):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 0.7)

        # EWT
        price_service.ethereum_network = EthereumNetwork.ENERGY_WEB_CHAIN
        with mock.patch.object(KrakenClient, "get_ewt_usd_price", return_value=0.9):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 0.9)

        # BINANCE
        price_service.ethereum_network = EthereumNetwork.BINANCE_SMART_CHAIN_MAINNET
        with mock.patch.object(KucoinClient, "get_bnb_usd_price", return_value=1.2):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 1.2)

        # Gather
        price_service.ethereum_network = EthereumNetwork.GATHER_MAINNET_NETWORK
        with mock.patch.object(
            CoingeckoClient, "get_gather_usd_price", return_value=1.7
        ):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 1.7)

        # Avalanche
        price_service.ethereum_network = EthereumNetwork.AVALANCHE_C_CHAIN
        with mock.patch.object(KrakenClient, "get_avax_usd_price", return_value=6.5):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 6.5)

        # Aurora
        price_service.ethereum_network = EthereumNetwork.AURORA_MAINNET
        with mock.patch.object(KucoinClient, "get_aurora_usd_price", return_value=1.3):
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 1.3)

        # Cronos
        with mock.patch.object(KucoinClient, "get_cro_usd_price", return_value=4.4):
            price_service.ethereum_network = EthereumNetwork.CRONOS_MAINNET_BETA
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 4.4)

        # KuCoin
        with mock.patch.object(KucoinClient, "get_kcs_usd_price", return_value=4.4):
            price_service.ethereum_network = EthereumNetwork.KCC_MAINNET
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 4.4)

        # Milkomeda Cardano
        with mock.patch.object(KrakenClient, "get_ada_usd_price", return_value=5.5):
            price_service.ethereum_network = EthereumNetwork.MILKOMEDA_C1_MAINNET
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_native_coin_usd_price(), 5.5)

        # Milkomeda Algorand
        with mock.patch.object(KrakenClient, "get_algo_usd_price", return_value=6.6):
            price_service.ethereum_network = EthereumNetwork.MILKOMEDA_A1_MAINNET
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_algorand_usd_price(), 6.6)

        # XDC
        with mock.patch.object(KucoinClient, "get_xdc_usd_price", return_value=7.7):
            price_service.ethereum_network = EthereumNetwork.XINFIN_XDC_NETWORK
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_xdc_usd_price(), 7.7)

            price_service.ethereum_network = EthereumNetwork.XDC_APOTHEM_NETWORK
            price_service.cache_native_coin_usd_price.clear()
            self.assertEqual(price_service.get_xdc_usd_price(), 7.7)

    @mock.patch.object(CoingeckoClient, "get_bnb_usd_price", return_value=3.0)
    @mock.patch.object(KucoinClient, "get_bnb_usd_price", return_value=5.0)
    def test_get_binance_usd_price(
        self,
        get_bnb_usd_price_binance_mock: MagicMock,
        get_bnb_usd_price_coingecko: MagicMock,
    ):
        price_service = self.price_service

        price = price_service.get_binance_usd_price()
        self.assertEqual(price, 5.0)

        get_bnb_usd_price_binance_mock.side_effect = CannotGetPrice
        price = price_service.get_binance_usd_price()
        self.assertEqual(price, 3.0)

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
    @mock.patch.object(KucoinClient, "get_matic_usd_price", return_value=7.0)
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

    def test_get_token_eth_value(self):
        mainnet_node = just_test_if_mainnet_node()
        price_service = PriceService(EthereumClient(mainnet_node), self.redis)
        gno_token_address = "0x6810e776880C02933D47DB1b9fc05908e5386b96"
        token_eth_value = price_service.get_token_eth_value(gno_token_address)
        self.assertIsInstance(token_eth_value, float)
        self.assertGreater(token_eth_value, 0)

    @mock.patch.object(KyberOracle, "get_price", return_value=1.23, autospec=True)
    def test_get_token_eth_value_mocked(self, kyber_get_price_mock: MagicMock):
        price_service = self.price_service
        oracle_1 = mock.MagicMock()
        oracle_1.get_price.return_value = 1.23
        oracle_2 = mock.MagicMock()
        oracle_3 = mock.MagicMock()
        price_service.enabled_price_oracles = (oracle_1, oracle_2, oracle_3)
        self.assertEqual(len(price_service.enabled_price_oracles), 3)
        random_address = Account.create().address
        self.assertEqual(len(price_service.cache_token_eth_value), 0)

        self.assertEqual(price_service.get_token_eth_value(random_address), 1.23)
        self.assertEqual(price_service.cache_token_eth_value[(random_address,)], 1.23)

        # Make every oracle fail
        oracle_1.get_price.side_effect = OracleException
        oracle_2.get_price.side_effect = OracleException
        oracle_3.get_price.side_effect = OracleException

        # Check cache
        self.assertEqual(price_service.get_token_eth_value(random_address), 1.23)
        random_address_2 = Account.create().address
        self.assertEqual(price_service.get_token_eth_value(random_address_2), 0.0)
        self.assertEqual(price_service.cache_token_eth_value[(random_address,)], 1.23)
        self.assertEqual(price_service.cache_token_eth_value[(random_address_2,)], 0.0)

    @mock.patch.object(
        PriceService, "get_underlying_tokens", return_value=[], autospec=True
    )
    @mock.patch.object(
        PriceService, "get_token_eth_value", autospec=True, return_value=1.0
    )
    def test_get_token_eth_price_from_composed_oracles(
        self, get_token_eth_value_mock: MagicMock, price_service_mock: MagicMock
    ):
        price_service = self.price_service
        token_one = UnderlyingToken("0x48f07301E9E29c3C38a80ae8d9ae771F224f1054", 0.482)
        token_two = UnderlyingToken("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 0.376)
        token_three = UnderlyingToken("0xA0b86991c6218b36c1d19D4a2e9Eb0cE360", 0.142)
        price_service_mock.return_value = [token_one, token_two, token_three]
        curve_price = "0xe7ce624c00381b4b7abb03e633fb4acac4537dd6"
        eth_price = price_service.get_token_eth_price_from_composed_oracles(curve_price)
        self.assertEqual(eth_price, 1.0)
