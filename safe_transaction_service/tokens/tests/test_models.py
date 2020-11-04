from django.test import TestCase

from eth_account import Account

from ..models import Token
from .factories import TokenFactory


class TestModels(TestCase):
    def test_token_querysets(self):
        TokenFactory(decimals=None)
        self.assertEqual(Token.objects.erc20().count(), 0)
        self.assertEqual(Token.objects.erc721().count(), 1)
        TokenFactory(decimals=0)
        self.assertEqual(Token.objects.erc20().count(), 1)
        self.assertEqual(Token.objects.erc721().count(), 1)
        TokenFactory(decimals=4)
        self.assertEqual(Token.objects.erc20().count(), 2)
        self.assertEqual(Token.objects.erc721().count(), 1)
        TokenFactory(decimals=None)
        self.assertEqual(Token.objects.erc20().count(), 2)
        self.assertEqual(Token.objects.erc721().count(), 2)

    def test_token_create_truncate(self):
        max_length = 60
        long_name = 'CHA' + 'NA' * 30 + ' BATMAN'
        self.assertGreater(len(long_name), max_length)
        truncated_name = long_name[:max_length]
        token = Token.objects.create(address=Account.create().address,
                                     name=long_name,
                                     symbol=long_name,
                                     decimals=18,
                                     trusted=True)
        self.assertEqual(token.name, truncated_name)
        self.assertEqual(token.symbol, truncated_name)
