import logging
from unittest import mock
from unittest.mock import MagicMock

from django.urls import reverse
from django.utils import timezone

from eth_account import Account
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APITestCase

from gnosis.eth.ethereum_client import Erc20Info, Erc20Manager, InvalidERC20Info
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import Token
from ..services import PriceService
from ..services.price_service import FiatCode, FiatPriceWithTimestamp
from .factories import TokenFactory

logger = logging.getLogger(__name__)


class TestTokenViews(SafeTestCaseMixin, APITestCase):
    def test_token_view(self):
        invalid_address = "0x1234"
        response = self.client.get(reverse("v1:tokens:detail", args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        random_address = Account.create().address
        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.data,
            {"detail": ErrorDetail(string="Not found.", code="not_found")},
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
            },
        )

    @mock.patch.object(Erc20Manager, "get_info", autospec=True)
    def test_token_view_missing(self, get_token_info_mock: MagicMock):
        get_token_info_mock.side_effect = InvalidERC20Info
        random_address = Account.create().address
        self.assertEqual(Token.objects.count(), 0)
        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Token.objects.count(), 0)

        random_address = Account.create().address  # Use new address to skip caching
        get_token_info_mock.side_effect = None
        get_token_info_mock.return_value = Erc20Info("UXIO", "UXI", 18)
        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Token.objects.count(), 1)

        response = self.client.get(reverse("v1:tokens:detail", args=(random_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Token.objects.count(), 1)

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
                }
            ],
        )

    def test_token_price_view(self):
        invalid_address = "0x1234"
        response = self.client.get(
            reverse("v1:tokens:price-usd", args=(invalid_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        random_address = Account.create().address
        response = self.client.get(
            reverse("v1:tokens:price-usd", args=(random_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.data,
            {"detail": ErrorDetail(string="Not found.", code="not_found")},
        )

        token = TokenFactory(address=random_address, decimals=18)  # ERC20
        response = self.client.get(
            reverse("v1:tokens:price-usd", args=(token.address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["fiat_code"], "USD")
        self.assertEqual(response.data["fiat_price"], "0.0")
        self.assertTrue(response.data["timestamp"])

        fiat_price_with_timestamp = FiatPriceWithTimestamp(
            48.1516, FiatCode.USD, timezone.now()
        )
        fiat_price_with_timestamp_iterator = iter([fiat_price_with_timestamp])
        with mock.patch.object(
            PriceService,
            "get_cached_usd_values",
            autospec=True,
            return_value=fiat_price_with_timestamp_iterator,
        ):
            response = self.client.get(
                reverse("v1:tokens:price-usd", args=(token.address,))
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["fiat_code"], "USD")
            self.assertEqual(
                response.data["fiat_price"], str(fiat_price_with_timestamp.fiat_price)
            )
            self.assertTrue(response.data["timestamp"])

    @mock.patch.object(
        PriceService, "get_native_coin_usd_price", return_value=321.2, autospec=True
    )
    def test_token_price_view_address_0(
        self, get_native_coin_usd_price_mock: MagicMock
    ):
        token_address = "0x0000000000000000000000000000000000000000"

        response = self.client.get(
            reverse("v1:tokens:price-usd", args=(token_address,))
        )

        # Native token should be retrieved even if it is not part of the Token table
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["fiat_code"], "USD")
        self.assertEqual(response.data["fiat_price"], "321.2")
        self.assertTrue(response.data["timestamp"])
