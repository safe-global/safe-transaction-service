from django.contrib.auth.models import User
from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.tests.factories import (
    MultisigTransactionFactory,
    SafeStatusFactory,
)


class TestViews(SafeTestCaseMixin, APITestCase):
    def setUp(self) -> None:
        user, _ = User.objects.get_or_create(username="test", password="12345")
        token, _ = Token.objects.get_or_create(user=user)
        self.header = {"HTTP_AUTHORIZATION": "Token " + token.key}

    def test_analytics_multisig_txs_by_origin_view(self):
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-origin")
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-origin"), **self.header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        origin = "Millennium Falcon Navigation Computer"
        origin_2 = "HAL 9000"
        multisig_transaction = MultisigTransactionFactory(origin=origin)
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-origin"), **self.header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"origin": origin, "transactions": 1},
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin_2)

        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-origin"), **self.header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"origin": origin_2, "transactions": 3},
            {"origin": origin, "transactions": 1},
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin)

        # Check sorting by the biggest
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-origin"), **self.header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"origin": origin, "transactions": 4},
            {"origin": origin_2, "transactions": 3},
        ]
        self.assertEqual(response.data, expected)

        # Test filters
        origin_3 = "Skynet"
        safe_address = Account.create().address
        MultisigTransactionFactory(origin=origin_3, safe=safe_address)
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-origin")
            + f"?safe={safe_address}",
            **self.header,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"origin": origin_3, "transactions": 1},
        ]
        self.assertEqual(response.data, expected)

        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-origin")
            + f"?to={multisig_transaction.to}",
            **self.header,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"origin": multisig_transaction.origin, "transactions": 1},
        ]
        self.assertEqual(response.data, expected)

    def test_analytics_multisig_txs_by_safe_view(self):
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-safe")
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-safe"), **self.header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_address_1 = Account.create().address
        safe_address_2 = Account.create().address
        safe_address_3 = Account.create().address
        MultisigTransactionFactory(safe=safe_address_1)
        MultisigTransactionFactory(safe=safe_address_1)
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-safe"), **self.header
        )
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["results"][0],
            {"safe": safe_address_1, "masterCopy": None, "transactions": 2},
        )
        MultisigTransactionFactory(safe=safe_address_1)
        safe_status_1 = SafeStatusFactory(address=safe_address_1)
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-safe"), **self.header
        )
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result["count"], 1)
        self.assertIsNotNone(safe_status_1.master_copy)
        self.assertEqual(
            result["results"][0],
            {
                "safe": safe_address_1,
                "masterCopy": safe_status_1.master_copy,
                "transactions": 3,
            },
        )
        MultisigTransactionFactory(safe=safe_address_2)
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-safe"), **self.header
        )
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            result["results"],
            [
                {
                    "safe": safe_address_1,
                    "masterCopy": safe_status_1.master_copy,
                    "transactions": 3,
                },
                {"safe": safe_address_2, "masterCopy": None, "transactions": 1},
            ],
        )
        safe_status_2 = SafeStatusFactory(address=safe_address_2)
        safe_status_3 = SafeStatusFactory(address=safe_address_3)
        [MultisigTransactionFactory(safe=safe_address_3) for _ in range(4)]
        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-safe"), **self.header
        )
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            result["results"],
            [
                {
                    "safe": safe_address_3,
                    "masterCopy": safe_status_3.master_copy,
                    "transactions": 4,
                },
                {
                    "safe": safe_address_1,
                    "masterCopy": safe_status_1.master_copy,
                    "transactions": 3,
                },
                {
                    "safe": safe_address_2,
                    "masterCopy": safe_status_2.master_copy,
                    "transactions": 1,
                },
            ],
        )

        response = self.client.get(
            reverse("v1:analytics:analytics-multisig-txs-by-safe")
            + f"?master_copy={safe_status_1.master_copy}",
            **self.header,
        )
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            result["results"],
            [
                {
                    "safe": safe_address_1,
                    "masterCopy": safe_status_1.master_copy,
                    "transactions": 3,
                },
            ],
        )
