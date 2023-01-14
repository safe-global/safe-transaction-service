import json

from django.test import TestCase

from safe_transaction_service.analytics.services.analytics_service import (
    AnalyticsService,
)
from safe_transaction_service.analytics.tasks import get_transactions_per_safe_app_task
from safe_transaction_service.history.models import MultisigTransaction
from safe_transaction_service.history.tests.factories import MultisigTransactionFactory
from safe_transaction_service.utils.redis import get_redis


class TestTasks(TestCase):
    def test_get_transactions_per_safe_apps(self):
        redis = get_redis()
        redis.flushall()
        redis_key = AnalyticsService.REDIS_TRANSACTIONS_PER_SAFE_APP
        origin_1 = {"url": "https://example1.com", "name": "SafeApp1"}
        origin_2 = {"url": "https://example2.com", "name": "SafeApp2"}
        string_origin = "test"
        expected = [
            {
                "name": "SafeApp2",
                "url": "https://example2.com",
                "total_tx": 7,
                "tx_last_week": 7,
                "tx_last_month": 7,
                "tx_last_year": 7,
            },
            {
                "name": "SafeApp1",
                "url": "https://example1.com",
                "total_tx": 3,
                "tx_last_week": 3,
                "tx_last_month": 3,
                "tx_last_year": 3,
            },
        ]
        for _ in range(3):
            MultisigTransactionFactory(origin=origin_1)
        for _ in range(7):
            MultisigTransactionFactory(origin=origin_2)
        MultisigTransactionFactory(origin=string_origin)

        self.assertEqual(MultisigTransaction.objects.count(), 11)
        value = redis.get(redis_key)
        self.assertIsNone(value)
        # Execute the task to get data from database
        get_transactions_per_safe_app_task()
        # Get the result from redis
        value = redis.get(redis_key)
        analytic = json.loads(value)

        self.assertEqual(analytic, expected)
