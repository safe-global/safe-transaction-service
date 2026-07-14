# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from unittest import mock
from unittest.mock import MagicMock

from django.core.cache import cache
from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APITestCase
from safe_eth.eth.ethereum_client import (
    Erc20Info,
    Erc20Manager,
    Erc721Manager,
    InvalidERC20Info,
    InvalidERC721Info,
)
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import Token, TokenNotValid
from .factories import TokenFactory, TokenListFactory

logger = logging.getLogger(__name__)


class TestTokenViews(SafeTestCaseMixin, APITestCase):
    @mock.patch.object(
        Erc721Manager, "get_info", autospec=True, side_effect=InvalidERC721Info
    )
    @mock.patch.object(
        Erc20Manager, "get_info", autospec=True, side_effect=InvalidERC20Info
    )
    def test_token_view(
        self, erc20_get_info_mock: MagicMock, erc721_get_info_mock: MagicMock
    ):
        invalid_address = "0x1234"
        response = self.client.get(reverse("v1:tokens:detail", args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        random_address = Account.create().address
        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.data,
            {
                "detail": ErrorDetail(
                    string="No Token matches the given query.", code="not_found"
                )
            },
        )

        token = TokenFactory(address=random_address, decimals=18)  # ERC20
        response = self.client.get(reverse("v1:tokens:detail", args=(token.address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "type": "ERC20",
                "address": token.address,
                "logo_uri": token.get_full_logo_uri(),
                "name": token.name,
                "symbol": token.symbol,
                "decimals": token.decimals,
                "trusted": token.trusted,
            },
        )

        token = TokenFactory(decimals=None)  # ERC721
        response = self.client.get(reverse("v1:tokens:detail", args=(token.address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "type": "ERC721",
                "address": token.address,
                "logo_uri": token.get_full_logo_uri(),
                "name": token.name,
                "symbol": token.symbol,
                "decimals": token.decimals,
                "trusted": token.trusted,
            },
        )

    @mock.patch.object(
        Erc721Manager, "get_info", autospec=True, side_effect=InvalidERC721Info
    )
    @mock.patch.object(
        Erc20Manager, "get_info", autospec=True, side_effect=InvalidERC20Info
    )
    def test_token_view_missing(
        self, erc20_get_info_mock: MagicMock, erc721_get_info_mock: MagicMock
    ):
        # Not indexed and not a valid token on-chain: 404 and recorded as invalid
        random_address = Account.create().address
        self.assertEqual(Token.objects.count(), 0)
        self.assertEqual(TokenNotValid.objects.count(), 0)

        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Token.objects.count(), 0)
        self.assertEqual(
            TokenNotValid.objects.filter(address=random_address).count(), 1
        )

        # Second request short-circuits on TokenNotValid without another RPC call
        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        erc20_get_info_mock.assert_called_once()

    @mock.patch.object(
        Erc20Manager,
        "get_info",
        autospec=True,
        return_value=Erc20Info(name="Gnosis", symbol="GNO", decimals=18),
    )
    def test_token_view_lazy_creation(self, erc20_get_info_mock: MagicMock):
        # An unindexed but valid token is fetched from the blockchain on first request
        random_address = Account.create().address
        self.assertEqual(Token.objects.count(), 0)

        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Token.objects.count(), 1)
        self.assertEqual(response.data["type"], "ERC20")
        self.assertEqual(response.data["address"], random_address)
        self.assertEqual(response.data["name"], "Gnosis")
        self.assertEqual(response.data["symbol"], "GNO")
        self.assertEqual(response.data["decimals"], 18)

    @mock.patch.object(Erc20Manager, "get_info", autospec=True, side_effect=IOError)
    def test_token_view_blockchain_error(self, erc20_get_info_mock: MagicMock):
        # A node/RPC failure degrades to 404 (not 5xx) and is not blacklisted
        random_address = Account.create().address
        with self.assertLogs("safe_transaction_service.tokens.views", level="WARNING"):
            response = self.client.get(
                reverse("v1:tokens:detail", args=(random_address,))
            )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Token.objects.count(), 0)
        self.assertEqual(TokenNotValid.objects.count(), 0)
        erc20_get_info_mock.assert_called_once()

    def test_tokens_view(self):
        response = self.client.get(reverse("v1:tokens:list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

        token = TokenFactory()
        response = self.client.get(reverse("v1:tokens:list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"],
            [
                {
                    "type": "ERC20",
                    "address": token.address,
                    "logo_uri": token.get_full_logo_uri(),
                    "name": token.name,
                    "symbol": token.symbol,
                    "decimals": token.decimals,
                    "trusted": token.trusted,
                }
            ],
        )

    def test_token_lists_view(self):
        response = self.client.get(reverse("v1:tokens:token-lists"))
        self.assertEqual(response.data["results"], [])
        token_list = TokenListFactory()
        # Check cache
        self.assertEqual(response.data["results"], [])

        cache.clear()

        response = self.client.get(reverse("v1:tokens:token-lists"))
        self.assertEqual(
            response.data["results"],
            [
                {
                    "url": token_list.url,
                    "description": token_list.description,
                }
            ],
        )
