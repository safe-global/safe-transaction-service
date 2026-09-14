# SPDX-License-Identifier: FSL-1.1-MIT
from unittest import mock

from django.db import OperationalError, connections
from django.test import TestCase

from redis.exceptions import ConnectionError as RedisConnectionError

LIVE_URLS = ("/health/live", "/health/live/")
READY_URLS = ("/health/ready", "/health/ready/")


class TestHealthViews(TestCase):
    def test_live(self):
        for url in LIVE_URLS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_ready(self):
        for url in READY_URLS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(), {"ready": True, "db": True, "redis": True}
                )

    def test_ready_database_down(self):
        with mock.patch.object(
            connections["default"], "cursor", side_effect=OperationalError
        ):
            response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"ready": False, "db": False, "redis": True})

    def test_ready_redis_down(self):
        with mock.patch(
            "safe_transaction_service.utils.views.health.get_redis"
        ) as get_redis_mock:
            get_redis_mock.return_value.ping.side_effect = RedisConnectionError
            response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"ready": False, "db": True, "redis": False})

    def test_urls_are_not_redirected(self):
        for url in LIVE_URLS + READY_URLS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotIn(response.status_code, (301, 302))

    def test_check_url_still_works(self):
        response = self.client.get("/check/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Ok")
