from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.tests.factories import MultisigTransactionFactory

from ..tasks import get_transactions_per_safe_app_task


class TestViewsV2(SafeTestCaseMixin, APITestCase):
    def test_analytics_multisig_txs_by_origin_view(self):
        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        origin_1 = {"url": "https://example1.com", "name": "afeApp1"}
        origin_2 = {"url": "https://example2.com", "name": "afeApp2"}

        MultisigTransactionFactory(origin=origin_1)
        # Execute the periodic task
        get_transactions_per_safe_app_task()
        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"name": origin_1["name"], "url": origin_1["url"], "transactions": 1},
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin_2)

        # Execute the periodic task
        get_transactions_per_safe_app_task()

        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"name": origin_2["name"], "url": origin_2["url"], "transactions": 3},
            {"name": origin_1["name"], "url": origin_1["url"], "transactions": 1},
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin_1)

        # Execute the periodic task
        get_transactions_per_safe_app_task()
        # Check sorting by the biggest
        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {"name": origin_1["name"], "url": origin_1["url"], "transactions": 4},
            {"name": origin_2["name"], "url": origin_2["url"], "transactions": 3},
        ]
        self.assertEqual(response.data, expected)
