import json

from django.test import TestCase

from safe_transaction_service.analytics.tasks import get_transactions_per_safe_task
from safe_transaction_service.history.tests.factories import MultisigTransactionFactory
from safe_transaction_service.utils.redis import get_redis


class TestTasks(TestCase):
    def test_get_transactions_per_safe_apps(self):
        redis = get_redis()
        origin_1 = {"url": "https://example1.com", "name": "afeApp1"}
        origin_2 = {"url": "https://example2.com", "name": "afeApp2"}
        wrong_origin = "eoo"
        expected = [
            {
                "origin__name": "afeApp2",
                "origin__url": "https://example2.com",
                "transactions": 7,
            },
            {
                "origin__name": "afeApp1",
                "origin__url": "https://example1.com",
                "transactions": 3,
            },
        ]
        for _ in range(3):
            MultisigTransactionFactory(origin=origin_1)
        for _ in range(7):
            MultisigTransactionFactory(origin=origin_2)
        MultisigTransactionFactory(origin=wrong_origin)

        get_transactions_per_safe_task()
        value = redis.get("analytics_transactions_per_safe_app")
        analytic = json.loads(value)

        self.assertEqual(analytic, expected)
