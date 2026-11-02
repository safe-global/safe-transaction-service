# SPDX-License-Identifier: FSL-1.1-MIT
import unittest
from unittest.mock import MagicMock

from django.test import RequestFactory
from django.urls import clear_script_prefix

from ..proxy_prefix_middleware import ProxyPrefixMiddleware


class TestMiddlewares(unittest.TestCase):
    def tearDown(self):
        # ProxyPrefixMiddleware sets the script prefix of the thread, used by reverse()
        clear_script_prefix()

    def get_with_prefix(self, prefix: str):
        request = RequestFactory().get(
            "/test/path", headers={"X_FORWARDED_PREFIX": prefix}
        )
        ProxyPrefixMiddleware(MagicMock())(request)
        return request

    def test_proxy_prefix_middleware(self):
        request_factory = RequestFactory()
        get_response = MagicMock(return_value="middleware_response")
        request = request_factory.get("/test/path")

        middleware = ProxyPrefixMiddleware(get_response)
        response = middleware(request)

        get_response.assert_called_once_with(request)
        self.assertEqual(response, "middleware_response")
        self.assertEqual(request.build_absolute_uri(), "http://testserver/test/path")
        self.assertEqual(request.get_full_path(), "/test/path")

        get_response.reset_mock()
        prefix = "/prefix"
        request = request_factory.get(
            "/test/path", headers={"X_FORWARDED_PREFIX": prefix}
        )

        middleware = ProxyPrefixMiddleware(get_response)
        response = middleware(request)

        get_response.assert_called_once_with(request)
        self.assertEqual(response, "middleware_response")
        self.assertEqual(
            request.build_absolute_uri(), "http://testserver/prefix/test/path"
        )
        self.assertEqual(request.get_full_path(), "/prefix/test/path")

    def test_proxy_prefix_middleware_strips_trailing_slash(self):
        request = self.get_with_prefix("/prefix/")

        self.assertEqual(request.META["HTTP_X_FORWARDED_PREFIX"], "/prefix")
        self.assertEqual(
            request.build_absolute_uri(), "http://testserver/prefix/test/path"
        )
        self.assertEqual(request.get_full_path(), "/prefix/test/path")

    def test_proxy_prefix_middleware_slash_prefix_is_no_prefix(self):
        request = self.get_with_prefix("/")

        self.assertEqual(request.META["HTTP_X_FORWARDED_PREFIX"], "")
        self.assertEqual(request.build_absolute_uri(), "http://testserver/test/path")
        self.assertEqual(request.get_full_path(), "/test/path")
