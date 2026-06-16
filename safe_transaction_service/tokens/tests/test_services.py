# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import TestCase

from eth_account import Account

from ..models import Token
from ..services import TokenServiceProvider
from .factories import TokenFactory


class TokenServiceTestCase(TestCase):
    def setUp(self):
        TokenServiceProvider.del_singleton()

    def tearDown(self):
        TokenServiceProvider.del_singleton()

    def test_is_trusted(self):
        token_service = TokenServiceProvider()
        trusted_token = TokenFactory(trusted=True)
        TokenFactory(trusted=False)

        self.assertTrue(token_service.is_trusted(trusted_token.address))
        self.assertFalse(token_service.is_trusted(Account.create().address))

    def test_get_trusted_token_addresses(self):
        token_service = TokenServiceProvider()
        self.assertEqual(token_service.get_trusted_token_addresses(), frozenset())

        # Saving a Token fires the `post_save` signal that clears the cache
        trusted_token = TokenFactory(trusted=True)
        self.assertEqual(
            token_service.get_trusted_token_addresses(),
            frozenset({trusted_token.address}),
        )

    def test_cache_is_stale_until_cleared(self):
        token_service = TokenServiceProvider()
        token = TokenFactory(trusted=False)
        # Populate the cache while the token is not trusted
        self.assertEqual(token_service.get_trusted_token_addresses(), frozenset())

        # A bulk `update` does not fire the `post_save` signal, so the cache is
        # not invalidated and the change is not visible yet
        Token.objects.filter(address=token.address).update(trusted=True)
        self.assertEqual(token_service.get_trusted_token_addresses(), frozenset())

        # Clearing the cache (as the daily task does) makes the change visible
        token_service.cache_trusted_addresses.clear()
        self.assertEqual(
            token_service.get_trusted_token_addresses(), frozenset({token.address})
        )
