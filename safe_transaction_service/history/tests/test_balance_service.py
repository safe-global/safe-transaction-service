from unittest import mock
from unittest.mock import MagicMock

from django.conf import settings
from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClient
from gnosis.eth.oracles import (KyberOracle, OracleException, UniswapOracle,
                                UniswapV2Oracle)
from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin
from gnosis.eth.tests.utils import deploy_erc20

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.tests.factories import TokenFactory

from ..services import BalanceService, BalanceServiceProvider
from ..services.balance_service import BalanceWithFiat, CannotGetEthereumPrice
from .factories import EthereumEventFactory, SafeContractFactory
from .utils import just_test_if_mainnet_node


class TestBalanceService(EthereumTestCaseMixin, TestCase):
    @mock.patch.object(BalanceService, 'get_eth_usd_price_kraken', return_value=0.4)
    @mock.patch.object(BalanceService, 'get_eth_usd_price_binance', return_value=0.5)
    def test_get_eth_price(self, binance_mock: MagicMock, kraken_mock: MagicMock):
        balance_service = BalanceServiceProvider()
        eth_usd_price = balance_service.get_eth_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)
        binance_mock.assert_not_called()

        kraken_mock.side_effect = CannotGetEthereumPrice

        # Cache is still working
        eth_usd_price = balance_service.get_eth_price()
        self.assertEqual(eth_usd_price, kraken_mock.return_value)

        # Remove cache and test binance is called
        balance_service.cache_eth_price.clear()
        eth_usd_price = balance_service.get_eth_price()
        binance_mock.called_once()
        self.assertEqual(eth_usd_price, binance_mock.return_value)

    def test_get_dai_usd_price_kraken(self) -> float:
        just_test_if_mainnet_node()
        balance_service = BalanceServiceProvider()

        # Binance is used
        price = balance_service.get_dai_usd_price_kraken()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

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

    def test_get_ewt_usd_price_kucoin(self) -> float:
        just_test_if_mainnet_node()
        balance_service = BalanceServiceProvider()

        # Binance is used
        price = balance_service.get_ewt_usd_price_kucoin()
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)

    def test_token_eth_value(self):
        mainnet_node = just_test_if_mainnet_node()
        balance_service = BalanceService(EthereumClient(mainnet_node),
                                         settings.ETH_UNISWAP_FACTORY_ADDRESS,
                                         settings.ETH_KYBER_NETWORK_PROXY_ADDRESS)
        gno_token_address = '0x6810e776880C02933D47DB1b9fc05908e5386b96'
        token_eth_value = balance_service.get_token_eth_value(gno_token_address)
        self.assertIsInstance(token_eth_value, float)
        self.assertGreater(token_eth_value, 0)

    @mock.patch.object(KyberOracle, 'get_price', return_value=1.23, autospec=True)
    def test_token_eth_value_mocked(self, kyber_get_price_mock: MagicMock):
        balance_service = BalanceServiceProvider()
        random_address = Account.create().address
        self.assertEqual(len(balance_service.cache_token_eth_value), 0)
        self.assertEqual(balance_service.get_token_eth_value(random_address), 1.23)
        self.assertEqual(balance_service.cache_token_eth_value[(random_address,)], 1.23)

        # Every oracle is not accesible
        kyber_get_price_mock.side_effect = OracleException
        with mock.patch.object(UniswapOracle, 'get_price', side_effect=OracleException, autospec=True):
            with mock.patch.object(UniswapV2Oracle, 'get_price', side_effect=OracleException, autospec=True):
                self.assertEqual(balance_service.get_token_eth_value(random_address), 1.23)
                random_address_2 = Account.create().address
                self.assertEqual(balance_service.get_token_eth_value(random_address_2), 0.)
                self.assertEqual(balance_service.cache_token_eth_value[(random_address,)], 1.23)
                self.assertEqual(balance_service.cache_token_eth_value[(random_address_2,)], 0.)

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

    @mock.patch.object(BalanceService, 'get_token_eth_value', return_value=0.4, autospec=True)
    @mock.patch.object(BalanceService, 'get_eth_price', return_value=123.4, autospec=True)
    def test_get_usd_balances(self, get_eth_price_mock: MagicMock, get_token_eth_value_mock: MagicMock):
        balance_service = BalanceServiceProvider()

        safe_address = Account.create().address
        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)

        balances = balance_service.get_usd_balances(safe_address)
        self.assertEqual(len(balances), 1)
        self.assertIsNone(balances[0].token_address)
        self.assertEqual(balances[0].balance, value)

        tokens_value = int(12 * 1e18)
        erc20 = deploy_erc20(self.w3, 'Eurodollar', 'EUD', safe_address, tokens_value)
        balances = balance_service.get_usd_balances(safe_address)
        self.assertEqual(len(balances), 1)

        EthereumEventFactory(address=erc20.address, to=safe_address)
        balances = balance_service.get_usd_balances(safe_address)
        token_info = balance_service.get_token_info(erc20.address)
        self.assertCountEqual(balances, [
            BalanceWithFiat(None, None, value, 0.0, 123.4),
            BalanceWithFiat(
                erc20.address, token_info, tokens_value, round(123.4 * 0.4 * (tokens_value / 1e18), 4),
                round(123.4 * 0.4, 4)
            )
        ])

        balances = balance_service.get_usd_balances(safe_address, only_trusted=True)
        self.assertCountEqual(balances, [
            BalanceWithFiat(None, None, value, 0.0, 123.4),
        ])

        Token.objects.filter(address=erc20.address).update(trusted=True, spam=False)
        balances = balance_service.get_usd_balances(safe_address, only_trusted=True)
        self.assertCountEqual(balances, [
            BalanceWithFiat(None, None, value, 0.0, 123.4),
            BalanceWithFiat(
                erc20.address, token_info, tokens_value, round(123.4 * 0.4 * (tokens_value / 1e18), 4),
                round(123.4 * 0.4, 4)
            )
        ])

        # Test sorting
        erc20_2 = deploy_erc20(self.w3, 'Peseta', 'PTA', safe_address, tokens_value)
        token_info_2 = balance_service.get_token_info(erc20_2.address)
        erc20_3 = deploy_erc20(self.w3, 'Double Dollars', 'DD', safe_address, tokens_value)
        token_info_3 = balance_service.get_token_info(erc20_3.address)

        EthereumEventFactory(address=erc20_2.address, to=safe_address)
        EthereumEventFactory(address=erc20_3.address, to=safe_address)
        balances = balance_service.get_usd_balances(safe_address)
        token_info = balance_service.get_token_info(erc20.address)
        self.assertCountEqual(balances, [
            BalanceWithFiat(None, None, value, 0.0, 123.4),
            BalanceWithFiat(
                erc20_3.address, token_info_3, tokens_value, round(123.4 * 0.4 * (tokens_value / 1e18), 4),
                round(123.4 * 0.4, 4)
            ),
            BalanceWithFiat(
                erc20.address, token_info, tokens_value, round(123.4 * 0.4 * (tokens_value / 1e18), 4),
                round(123.4 * 0.4, 4)
            ),
            BalanceWithFiat(
                erc20_2.address, token_info_2, tokens_value, round(123.4 * 0.4 * (tokens_value / 1e18), 4),
                round(123.4 * 0.4, 4)
            ),
        ])

    def test_filter_addresses(self):
        balance_service = BalanceServiceProvider()
        db_not_trusted_addresses = [TokenFactory(trusted=False, spam=False).address for _ in range(3)]
        db_trusted_addresses = [TokenFactory(trusted=True).address for _ in range(2)]
        db_spam_address = TokenFactory(trusted=False, spam=True).address
        db_invalid_address = TokenFactory(decimals=None).address  # This should not be shown
        not_in_db_address = Account.create().address

        addresses = (db_not_trusted_addresses + db_trusted_addresses + [db_invalid_address]
                     + [not_in_db_address] + [db_spam_address])
        expected_address = db_not_trusted_addresses + db_trusted_addresses + [not_in_db_address] + [db_spam_address]
        self.assertCountEqual(balance_service._filter_addresses(addresses, False, False),
                              expected_address)

        expected_address = db_trusted_addresses
        self.assertCountEqual(balance_service._filter_addresses(addresses, True, False),
                              expected_address)

        expected_address = db_not_trusted_addresses + db_trusted_addresses
        self.assertCountEqual(balance_service._filter_addresses(addresses, False, True),
                              expected_address)
