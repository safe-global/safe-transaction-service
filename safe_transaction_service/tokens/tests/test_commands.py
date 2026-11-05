# SPDX-License-Identifier: FSL-1.1-MIT
from io import StringIO
from unittest import mock
from unittest.mock import MagicMock

from django.core.management import call_command
from django.test import TestCase

from eth_account import Account
from safe_eth.eth.ethereum_client import Erc20Info, Erc20Manager
from safe_eth.eth.tests.ethereum_test_case import EthereumTestCaseMixin
from safe_eth.eth.tests.utils import deploy_erc20

from ..clients import CoinMarketCapClient, CoinMarketCapToken
from ..models import Token
from .factories import TokenFactory

coinmarketcap_client_mock = [
    CoinMarketCapToken(
        id=1659,
        name="Gnosis",
        symbol="GNO",
        token_address="0x6810e776880C02933D47DB1b9fc05908e5386b96",
        logo_uri="https://s2.coinmarketcap.com/static/img/coins/200x200/1659.png",
    ),
]

relay_token_client_mock = [
    {
        "address": "0x6810e776880C02933D47DB1b9fc05908e5386b96",
        "logoUri": "https://tokens-logo.localhost/0x6810e776880C02933D47DB1b9fc05908e5386b96.png",
        "default": False,
        "name": "Gnosis",
        "symbol": "GNO",
        "description": "Crowd Sourced Wisdom - The next generation blockchain network. Speculate on anything with an easy-to-use prediction market",
        "decimals": 18,
        "websiteUri": "https://safe.global",
        "gas": False,
    },
    {
        "address": "0x1A5F9352Af8aF974bFC03399e3767DF6370d82e4",
        "logoUri": "https://tokens-logo.localhost/0x1A5F9352Af8aF974bFC03399e3767DF6370d82e4.png",
        "default": True,
        "name": "OWL Token",
        "symbol": "OWL",
        "description": "",
        "decimals": 18,
        "websiteUri": "https://owl.safe_eth.io/",
        "gas": True,
    },
]


class TestCommands(EthereumTestCaseMixin, TestCase):
    def test_add_token(self):
        command = "add_token"
        buf = StringIO()
        token = TokenFactory(trusted=False)
        self.assertFalse(token.trusted)

        call_command(command, token.address, stdout=buf)
        self.assertIn("already exists", buf.getvalue())
        token.refresh_from_db()
        self.assertTrue(token.trusted)
        self.assertTrue(token.trusted_admin)

        erc20 = deploy_erc20(
            self.ethereum_client.w3,
            self.ethereum_test_account,
            "Uxio",
            "UXI",
            Account.create().address,
            10,
        )
        call_command(command, erc20.address, "--no-prompt", stdout=buf)
        self.assertIn("Created token", buf.getvalue())
        created_token = Token.objects.get(address=erc20.address)
        self.assertTrue(created_token.trusted)
        self.assertTrue(created_token.trusted_admin)

    def test_add_token_trusts_a_token_already_on_a_list(self):
        # Trusted from a token list, but never curated
        token = TokenFactory(trusted=True)
        self.assertFalse(token.trusted_admin)

        call_command("add_token", token.address, stdout=StringIO())
        token.refresh_from_db()
        self.assertTrue(token.trusted_admin)

    @mock.patch.object(
        Erc20Manager,
        "get_info",
        autospec=True,
        return_value=Erc20Info("Gnosis", "GNO", 18),
    )
    @mock.patch.object(
        CoinMarketCapClient,
        "get_ethereum_tokens",
        autospec=True,
        return_value=coinmarketcap_client_mock,
    )
    def test_update_tokens_from_coinmarketcap(
        self,
        coinmarketcap_client_get_ethereum_tokens_mock: MagicMock,
        erc20_manager_get_info_mock: MagicMock,
    ):
        command = "update_tokens_from_coinmarketcap"
        buf = StringIO()

        self.assertEqual(Token.objects.count(), 0)
        call_command(command, "fake-api-key", stdout=buf)
        self.assertEqual(Token.objects.count(), 0)
        call_command(command, "fake-api-key", "--store-db", stdout=buf)
        self.assertEqual(Token.objects.count(), 1)
        self.assertTrue(Token.objects.first().trusted)
        Token.objects.update(trusted=False)

        call_command(command, "fake-api-key", "--store-db", stdout=buf)
        self.assertTrue(Token.objects.first().trusted)
        # Bulk ingestion is not curation, the daily task can still untrust them
        self.assertFalse(Token.objects.first().trusted_admin)
