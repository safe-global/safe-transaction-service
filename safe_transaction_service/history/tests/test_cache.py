from django.test import TestCase

from safe_transaction_service.history.cache import CacheSafeTxsView


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
