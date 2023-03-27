import json
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from django_test_migrations.migrator import Migrator
from eth_account import Account
from web3 import Web3

from gnosis.eth import EthereumNetwork


class TestMigrations(TestCase):
    def setUp(self) -> None:
        self.migrator = Migrator(database="default")

    @mock.patch(
        "safe_transaction_service.tokens.migrations.0010_tokenlist.get_ethereum_network",
        return_value=EthereumNetwork.MAINNET,
    )
    def test_migration_forward_0010(self, get_ethereum_network_mock: MagicMock):
        """
        Add
        """
        old_state = self.migrator.apply_initial_migration(
            ("tokens", "0009_token_token_spam_idx")
        )

        new_state = self.migrator.apply_tested_migration(("tokens", "0010_tokenlist"))
        TokenList = new_state.apps.get_model("tokens", "TokenList")
        token_list = TokenList.objects.get()
        self.assertEqual(
            token_list.url, "https://tokens.coingecko.com/uniswap/all.json"
        )
        self.assertEqual(token_list.description, "Coingecko")

    @mock.patch(
        "safe_transaction_service.tokens.migrations.0010_tokenlist.get_ethereum_network",
        return_value=EthereumNetwork.AIOZ_NETWORK,
    )
    def test_migration_forward_0010_network_without_data(
        self, get_ethereum_network_mock: MagicMock
    ):
        old_state = self.migrator.apply_initial_migration(
            ("tokens", "0009_token_token_spam_idx")
        )

        new_state = self.migrator.apply_tested_migration(("tokens", "0010_tokenlist"))
        TokenList = new_state.apps.get_model("tokens", "TokenList")
        self.assertEqual(TokenList.objects.count(), 0)
