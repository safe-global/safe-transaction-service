from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from eth_account import Account

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin
from gnosis.eth.tests.utils import deploy_erc20

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.services.price_service import PriceService
from safe_transaction_service.tokens.tests.factories import TokenFactory

from ..services import BalanceServiceProvider
from ..services.balance_service import BalanceWithFiat
from .factories import EthereumEventFactory, SafeContractFactory


class TestBalanceService(EthereumTestCaseMixin, TestCase):
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

    @mock.patch.object(PriceService, 'get_token_eth_value', return_value=0.4, autospec=True)
    @mock.patch.object(PriceService, 'get_eth_usd_price', return_value=123.4, autospec=True)
    @mock.patch.object(timezone, 'now', return_value=timezone.now())
    def test_get_usd_balances(self, timezone_now_mock: MagicMock, get_eth_usd_price_mock: MagicMock,
                              get_token_eth_value_mock: MagicMock):
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
            BalanceWithFiat(
                None, None, value, 1., timezone_now_mock.return_value, 0.0, 123.4
            ),
            BalanceWithFiat(
                erc20.address, token_info, tokens_value, 0.4, timezone_now_mock.return_value,
                round(123.4 * 0.4 * (tokens_value / 1e18), 4), round(123.4 * 0.4, 4)
            )
        ])

        balances = balance_service.get_usd_balances(safe_address, only_trusted=True)
        self.assertCountEqual(balances, [
            BalanceWithFiat(
                None, None, value, 1., timezone_now_mock.return_value, 0., 123.4
            ),
        ])

        Token.objects.filter(address=erc20.address).update(trusted=True, spam=False)
        balances = balance_service.get_usd_balances(safe_address, only_trusted=True)
        self.assertCountEqual(balances, [
            BalanceWithFiat(
                None, None, value, 1., timezone_now_mock.return_value, 0., 123.4
            ),
            BalanceWithFiat(
                erc20.address, token_info, tokens_value, 0.4, timezone_now_mock.return_value,
                round(123.4 * 0.4 * (tokens_value / 1e18), 4), round(123.4 * 0.4, 4)
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
            BalanceWithFiat(
                None, None, value, 1., timezone_now_mock.return_value, 0., 123.4
            ),
            BalanceWithFiat(
                erc20_3.address, token_info_3, tokens_value, 0.4, timezone_now_mock.return_value,
                round(123.4 * 0.4 * (tokens_value / 1e18), 4), round(123.4 * 0.4, 4)
            ),
            BalanceWithFiat(
                erc20.address, token_info, tokens_value, 0.4, timezone_now_mock.return_value,
                round(123.4 * 0.4 * (tokens_value / 1e18), 4), round(123.4 * 0.4, 4)
            ),
            BalanceWithFiat(
                erc20_2.address, token_info_2, tokens_value, 0.4, timezone_now_mock.return_value,
                round(123.4 * 0.4 * (tokens_value / 1e18), 4), round(123.4 * 0.4, 4)
            ),
        ])

    def test_filter_addresses(self):
        balance_service = BalanceServiceProvider()
        db_not_trusted_addresses = [TokenFactory(trusted=False, spam=False).address for _ in range(3)]
        db_trusted_addresses = [TokenFactory(trusted=True).address for _ in range(2)]
        db_spam_address = TokenFactory(trusted=False, spam=True).address
        db_invalid_address = TokenFactory(decimals=None).address  # This should not be shown
        db_events_bugged_erc20_address = TokenFactory(events_bugged=True).address  # This should be shown always
        db_events_bugged_not_erc20 = TokenFactory(decimals=None, events_bugged=True).address  # This should not be shown
        not_in_db_address = Account.create().address

        addresses = (db_not_trusted_addresses + db_trusted_addresses + [db_invalid_address]
                     + [not_in_db_address] + [db_spam_address])

        expected_address = (db_not_trusted_addresses + db_trusted_addresses + [not_in_db_address] + [db_spam_address]
                            + [db_events_bugged_erc20_address])

        self.assertCountEqual(balance_service._filter_addresses(addresses, False, False),
                              expected_address)

        expected_address = db_trusted_addresses
        self.assertCountEqual(balance_service._filter_addresses(addresses, True, False),
                              expected_address)

        Token.objects.filter(address=db_events_bugged_erc20_address).update(trusted=True)
        expected_address = db_trusted_addresses + [db_events_bugged_erc20_address]
        self.assertCountEqual(balance_service._filter_addresses(addresses, True, False),
                              expected_address)

        expected_address = db_not_trusted_addresses + db_trusted_addresses + [db_events_bugged_erc20_address]
        self.assertCountEqual(balance_service._filter_addresses(addresses, False, True),
                              expected_address)
