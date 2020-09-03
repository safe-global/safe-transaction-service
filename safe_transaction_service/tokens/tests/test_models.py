from django.test import TestCase

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
