import importlib
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from django_test_migrations.migrator import Migrator
from safe_eth.eth import EthereumNetwork

# https://github.com/python/cpython/issues/100950
token_list_migration = importlib.import_module(
    "safe_transaction_service.tokens.migrations.0010_tokenlist"
)


class TestMigrations(TestCase):
    def setUp(self) -> None:
        self.migrator = Migrator(database="default")

    @mock.patch(
        f"{__name__}.token_list_migration.get_ethereum_network",
        return_value=EthereumNetwork.MAINNET,
    )
    def test_migration_forward_0010(self, get_ethereum_network_mock: MagicMock):
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
        f"{__name__}.token_list_migration.get_ethereum_network",
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
