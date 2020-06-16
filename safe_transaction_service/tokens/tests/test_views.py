import logging

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APITestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from .factories import TokenFactory

logger = logging.getLogger(__name__)


class TestTokenViews(SafeTestCaseMixin, APITestCase):
    def test_token_view(self):
        random_address = Account.create().address
        response = self.client.get(reverse('v1:token', args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data, {'detail': ErrorDetail(string='Not found.', code='not_found')})

        token = TokenFactory(address=random_address)
        response = self.client.get(reverse('v1:token', args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'address': random_address,
                                         'logo_uri': token.get_full_logo_uri(),
                                         'name': token.name,
                                         'symbol': token.symbol,
                                         'decimals': token.decimals,
                                         'trusted': token.trusted})

    def test_tokens_view(self):
        response = self.client.get(reverse('v1:tokens'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

        token = TokenFactory()
        response = self.client.get(reverse('v1:tokens'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'], [{'address': token.address,
                                                     'logo_uri': token.get_full_logo_uri(),
                                                     'name': token.name,
                                                     'symbol': token.symbol,
                                                     'decimals': token.decimals,
                                                     'trusted': token.trusted}])
