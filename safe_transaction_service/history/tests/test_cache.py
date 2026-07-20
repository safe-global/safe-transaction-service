# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import TestCase

from gevent.testing import mock

from safe_transaction_service.history.cache import (
    CacheSafeTxsView,
    remove_cache_view_for_addresses,
)


class TestCacheSafeTxsView(TestCase):
    def test_cache_name(self):
        safe_address = "0x5af394e41D387d507DA9a07D33d47Cf9D8Da656d"
        cache_tag = "testtag"
        cache_instance = CacheSafeTxsView(cache_tag, safe_address)
        self.assertEqual(
            cache_instance.cache_name,
            "testtag:0x5af394e41D387d507DA9a07D33d47Cf9D8Da656d",
        )

    def test_set_and_get_cache_data(self):
        safe_address = "0x5af394e41D387d507DA9a07D33d47Cf9D8Da656d"
        cache_tag = "testtag"
        cache_path = "cache_path"
        some_data = "TestData"
        cache_instance = CacheSafeTxsView(cache_tag, safe_address)
        cache_instance.set_cache_data(cache_path, some_data, 120)
        self.assertEqual(
            some_data, cache_instance.get_cache_data(cache_path).decode("utf-8")
        )

    @mock.patch(
        "safe_transaction_service.history.views.settings.CACHE_VIEW_DEFAULT_TIMEOUT",
        0,
    )
    def test_disable_cache(self):
        # CACHE_VIEW_DEFAULT_TIMEOUT equals to 0 disable the cache storing
        safe_address = "0x5af394e41D387d507DA9a07D33d47Cf9D8Da656d"
        cache_tag = "testtag"
        cache_path = "cache_path"
        some_data = "TestData"
        cache_instance = CacheSafeTxsView(cache_tag, safe_address)
        self.assertFalse(cache_instance.enabled)
        cache_instance.set_cache_data(cache_path, some_data, 120)
        self.assertIsNone(cache_instance.get_cache_data(cache_path))

    def test_remove_cache(self):
        safe_address = "0x5af394e41D387d507DA9a07D33d47Cf9D8Da656d"
        cache_tag = "testtag"
        cache_path = "cache_path"
        some_data = "TestData"
        cache_instance = CacheSafeTxsView(cache_tag, safe_address)
        cache_instance.set_cache_data(cache_path, some_data, 120)
        self.assertEqual(
            some_data, cache_instance.get_cache_data(cache_path).decode("utf-8")
        )
        cache_instance.remove_cache()
        self.assertIsNone(cache_instance.get_cache_data(cache_path))

    def test_remove_cache_view_for_addresses_without_transaction(self):
        # With no transaction open the removal must be immediate, without
        # registering any `on_commit` callback
        safe_address = "0x5af394e41D387d507DA9a07D33d47Cf9D8Da656d"
        connection_mock = mock.MagicMock(in_atomic_block=False)
        with (
            mock.patch(
                "safe_transaction_service.history.cache.transaction.get_connection",
                return_value=connection_mock,
            ),
            mock.patch(
                "safe_transaction_service.history.cache.remove_cache_views"
            ) as remove_cache_views_mock,
        ):
            remove_cache_view_for_addresses("testtag", [safe_address])

        remove_cache_views_mock.assert_called_once_with([f"testtag:{safe_address}"])
        connection_mock.on_commit.assert_not_called()
