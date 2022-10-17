from io import StringIO
from unittest import mock
from unittest.mock import MagicMock

from django.core.management import call_command
from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClientProvider
from gnosis.eth.ethereum_client import Erc20Info, Erc20Manager
from gnosis.eth.tests.utils import deploy_example_erc20

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
        "websiteUri": "https://gnosis.pm",
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
        "websiteUri": "https://owl.gnosis.io/",
        "gas": True,
    },
]


class TestCommands(TestCase):
    def test_add_token(self):
        command = "add_token"
        buf = StringIO()
        token = TokenFactory(trusted=False)
        self.assertFalse(token.trusted)

        call_command(command, token.address, stdout=buf)
        self.assertIn("already exists", buf.getvalue())
        token.refresh_from_db()
        self.assertTrue(token.trusted)

        ethereum_client = EthereumClientProvider()
        erc20 = deploy_example_erc20(ethereum_client.w3, 10, Account.create().address)
        call_command(command, erc20.address, "--no-prompt", stdout=buf)
        self.assertIn("Created token", buf.getvalue())
        self.assertTrue(Token.objects.get(address=erc20.address).trusted)

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
