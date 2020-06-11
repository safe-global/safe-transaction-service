from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClientProvider
from gnosis.eth.tests.utils import deploy_example_erc20

from .factories import TokenFactory


class TestCommands(TestCase):
    def test_add_token(self):
        token = TokenFactory()
        buf = StringIO()
        call_command('add_token', token.address, stdout=buf)
        self.assertIn('already exists', buf.getvalue())

        ethereum_client = EthereumClientProvider()
        erc20 = deploy_example_erc20(ethereum_client.w3, 10, Account.create().address)
        call_command('add_token', erc20.address, '--no-prompt', stdout=buf)
        self.assertIn('Created token', buf.getvalue())
