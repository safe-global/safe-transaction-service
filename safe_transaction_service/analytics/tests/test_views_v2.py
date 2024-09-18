from django.contrib.auth.models import User
from django.urls import reverse

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.tests.factories import MultisigTransactionFactory

from ...utils.redis import get_redis
from ..tasks import get_transactions_per_safe_app_task


class TestViewsV2(SafeTestCaseMixin, APITestCase):
    def test_analytics_multisig_txs_by_origin_view(self):
        redis = get_redis()
        redis.flushall()
        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin")
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        user, _ = User.objects.get_or_create(username="test", password="12345")
        token, _ = Token.objects.get_or_create(user=user)
        header = {"HTTP_AUTHORIZATION": "Token " + token.key}
        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin"), **header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

        origin_1 = {"url": "https://example1.com", "name": "SafeApp1"}
        origin_2 = {"url": "https://example2.com", "name": "SafeApp2"}

        MultisigTransactionFactory(origin=origin_1)
        # Execute the periodic task
        get_transactions_per_safe_app_task()
        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin"), **header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {
                "name": origin_1["name"],
                "url": origin_1["url"],
                "total_tx": 1,
                "tx_last_month": 1,
                "tx_last_week": 1,
                "tx_last_year": 1,
            },
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin_2)

        # Execute the periodic task
        get_transactions_per_safe_app_task()

        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin"), **header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {
                "name": origin_2["name"],
                "url": origin_2["url"],
                "total_tx": 3,
                "tx_last_month": 3,
                "tx_last_week": 3,
                "tx_last_year": 3,
            },
            {
                "name": origin_1["name"],
                "url": origin_1["url"],
                "total_tx": 1,
                "tx_last_month": 1,
                "tx_last_week": 1,
                "tx_last_year": 1,
            },
        ]
        self.assertEqual(response.data, expected)

        for _ in range(3):
            MultisigTransactionFactory(origin=origin_1)

        # Execute the periodic task
        get_transactions_per_safe_app_task()
        # Check sorting by the biggest
        response = self.client.get(
            reverse("v2:analytics:analytics-multisig-txs-by-origin"), **header
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected = [
            {
                "name": origin_1["name"],
                "url": origin_1["url"],
                "total_tx": 4,
                "tx_last_month": 4,
                "tx_last_week": 4,
                "tx_last_year": 4,
            },
            {
                "name": origin_2["name"],
                "url": origin_2["url"],
                "total_tx": 3,
                "tx_last_month": 3,
                "tx_last_week": 3,
                "tx_last_year": 3,
            },
        ]
        self.assertEqual(response.data, expected)
