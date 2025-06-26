import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from safe_transaction_service.middlewares import ProxyPrefixMiddleware


class TestProxyPrefixMiddleware(unittest.TestCase):
    def setUp(self):
        self.get_response = MagicMock(return_value="middleware_response")

    def test_no_prefix(self):
        request = SimpleNamespace(
            META={}, get_full_path=lambda force_append_slash=False: "/test/path"
        )

        middleware = ProxyPrefixMiddleware(self.get_response)
        response = middleware(request)

        self.get_response.assert_called_once_with(request)
        self.assertEqual(response, "middleware_response")
        self.assertEqual(request.get_full_path(), "/test/path")

    def test_with_prefix(self):
        prefix = "/prefix"
        request = SimpleNamespace(
            META={"HTTP_X_FORWARDED_PREFIX": prefix},
            get_full_path=lambda force_append_slash=False: "/test/path",
        )

        middleware = ProxyPrefixMiddleware(self.get_response)
        response = middleware(request)

        self.get_response.assert_called_once_with(request)
        self.assertEqual(response, "middleware_response")
        self.assertEqual(request.get_full_path(), f"{prefix}/test/path")
