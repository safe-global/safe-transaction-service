from unittest import mock
from unittest.mock import MagicMock

from django.conf import settings
from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClient
from gnosis.eth.ethereum_client import Erc20Info
from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from safe_transaction_service.tokens.tests.factories import TokenFactory

from ..services import BalanceService, BalanceServiceProvider
from ..services.balance_service import BalanceWithUsd, CannotGetEthereumPrice
from .factories import EthereumEventFactory, SafeContractFactory
from .utils import just_test_if_mainnet_node


class TestBalanceService(EthereumTestCaseMixin, TestCase):
    @mock.patch.object(BalanceService, 'get_eth_usd_price_kraken', return_value=0.4)
    @mock.patch.object(BalanceService, 'get_eth_usd_price_binance', return_value=0.5)
    def test_get_eth_usd_price(self, binance_mock: MagicMock, kraken_mock: MagicMock):
        balance_service = BalanceServiceProvider()
        eth_usd_price = balance_service.get_eth_usd_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)
        binance_mock.assert_not_called()

        kraken_mock.side_effect = CannotGetEthereumPrice

        # Cache is still working
        eth_usd_price = balance_service.get_eth_usd_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)

        # Remove cache and test binance is called
        balance_service.cache_eth_usd_price.clear()
        eth_usd_price = balance_service.get_eth_usd_price()
        binance_mock.called_once()
        self.assertEqual(eth_usd_price, binance_mock.return_value)

    def test_get_eth_usd_price_binance(self):
        just_test_if_mainnet_node()
        balance_service = BalanceServiceProvider()

        # Binance is used
        eth_usd_price = balance_service.get_eth_usd_price_binance()
        self.assertIsInstance(eth_usd_price, float)
        self.assertGreater(eth_usd_price, 0)

    def test_get_eth_usd_price_kraken(self):
        just_test_if_mainnet_node()
        balance_service = BalanceServiceProvider()

        # Kraken is used
        eth_usd_price = balance_service.get_eth_usd_price_kraken()
        self.assertIsInstance(eth_usd_price, float)
        self.assertGreater(eth_usd_price, 0)

    def test_token_eth_value(self):
        mainnet_node = just_test_if_mainnet_node()
        balance_service = BalanceService(EthereumClient(mainnet_node),
                                         settings.ETH_UNISWAP_FACTORY_ADDRESS,
                                         settings.ETH_KYBER_NETWORK_PROXY_ADDRESS)
        gno_token_address = '0x6810e776880C02933D47DB1b9fc05908e5386b96'
        token_eth_value = balance_service.get_token_eth_value(gno_token_address)
        self.assertIsInstance(token_eth_value, float)
        self.assertGreater(token_eth_value, 0)

    def test_get_token_info(self):
        balance_service = BalanceServiceProvider()
        token_address = Account.create().address
        self.assertIsNone(balance_service.get_token_info(token_address))

        token_db = TokenFactory(address=token_address)
        self.assertIsNone(balance_service.get_token_info(token_address))  # It's cached

        balance_service.cache_token_info = {}  # Empty cache
        token_info = balance_service.get_token_info(token_address)  # It's cached
        self.assertEqual(token_info.address, token_address)
        self.assertEqual(token_info.name, token_db.name)
        self.assertEqual(token_info.symbol, token_db.symbol)
        self.assertEqual(token_info.decimals, token_db.decimals)

    @mock.patch.object(BalanceService, 'get_token_info', autospec=True)
    @mock.patch.object(BalanceService, 'get_token_eth_value', return_value=0.4, autospec=True)
    @mock.patch.object(BalanceService, 'get_eth_usd_price', return_value=123.4, autospec=True)
    def test_get_usd_balances(self, get_eth_usd_price_mock: MagicMock, get_token_eth_value_mock: MagicMock,
                              get_token_info_mock: MagicMock):
        balance_service = BalanceServiceProvider()
        erc20_info = Erc20Info('UXIO', 'UXI', 18)
        get_token_info_mock.return_value = erc20_info

        safe_address = Account.create().address
        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)

        balances = balance_service.get_usd_balances(safe_address)
        self.assertEqual(len(balances), 1)
        self.assertIsNone(balances[0].token_address)
        self.assertEqual(balances[0].balance, value)

        tokens_value = int(12 * 1e18)
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        balances = balance_service.get_usd_balances(safe_address)
        self.assertEqual(len(balances), 1)

        EthereumEventFactory(address=erc20.address, to=safe_address)
        balances = balance_service.get_usd_balances(safe_address)
        self.assertCountEqual(balances, [BalanceWithUsd(None, None, value, 0.0),
                                         BalanceWithUsd(erc20.address, erc20_info,
                                                        tokens_value, round(123.4 * 0.4 * (tokens_value / 1e18), 4))
                                         ])
