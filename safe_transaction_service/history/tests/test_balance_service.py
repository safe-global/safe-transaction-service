from django.test import TestCase

from eth_account import Account
from safe_eth.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.tests.factories import TokenFactory

from ..services import BalanceServiceProvider


class TestBalanceService(EthereumTestCaseMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.balance_service = BalanceServiceProvider()

    def test_get_token_info(self):
        balance_service = self.balance_service
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

    def test_filter_addresses(self):
        balance_service = self.balance_service
        db_not_trusted_addresses = [
            TokenFactory(trusted=False, spam=False).address for _ in range(3)
        ]
        db_trusted_addresses = [TokenFactory(trusted=True).address for _ in range(2)]
        db_spam_address = TokenFactory(trusted=False, spam=True).address
        db_invalid_address = TokenFactory(
            decimals=None
        ).address  # This should not be shown
        db_events_bugged_erc20_address = TokenFactory(
            events_bugged=True
        ).address  # This should be shown always
        db_events_bugged_not_erc20 = TokenFactory(
            decimals=None, events_bugged=True
        ).address  # This should not be shown
        not_in_db_address = Account.create().address

        addresses = (
            db_not_trusted_addresses
            + db_trusted_addresses
            + [db_invalid_address]
            + [not_in_db_address]
            + [db_spam_address]
        )

        expected_address = (
            db_not_trusted_addresses
            + db_trusted_addresses
            + [not_in_db_address]
            + [db_spam_address]
            + [db_events_bugged_erc20_address]
        )

        self.assertCountEqual(
            balance_service._filter_addresses(addresses, False, False), expected_address
        )

        expected_address = db_trusted_addresses
        self.assertCountEqual(
            balance_service._filter_addresses(addresses, True, False), expected_address
        )

        Token.objects.filter(address=db_events_bugged_erc20_address).update(
            trusted=True
        )
        expected_address = db_trusted_addresses + [db_events_bugged_erc20_address]
        self.assertCountEqual(
            balance_service._filter_addresses(addresses, True, False), expected_address
        )

        expected_address = (
            db_not_trusted_addresses
            + db_trusted_addresses
            + [db_events_bugged_erc20_address]
        )
        self.assertCountEqual(
            balance_service._filter_addresses(addresses, False, True), expected_address
        )
