# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import TestCase, override_settings

from safe_transaction_service.utils.redis import get_redis


class TestGetRedis(TestCase):
    def tearDown(self):
        get_redis.cache_clear()

    @override_settings(REDIS_POOL_MAX_CONNECTIONS=1234)
    def test_get_redis_pool_max_connections(self):
        get_redis.cache_clear()
        redis = get_redis()
        self.assertEqual(redis.connection_pool.max_connections, 1234)
