import unittest
from unittest.mock import MagicMock

from django.test import RequestFactory

from ..middlewares import ProxyPrefixMiddleware


class TestMiddlewares(unittest.TestCase):

    def test_proxy_prefix_middleware(self):
        request_factory = RequestFactory()
        get_response = MagicMock(return_value="middleware_response")
        request = request = request_factory.get("/test/path")

        middleware = ProxyPrefixMiddleware(get_response)
        response = middleware(request)

        get_response.assert_called_once_with(request)
        self.assertEqual(response, "middleware_response")
        self.assertEqual(request.build_absolute_uri(), "http://testserver/test/path")

        get_response.reset_mock()
        prefix = "/prefix"
        request = request = request_factory.get(
            "/test/path", headers={"HTTP_X_FORWARDED_PREFIX": prefix}
        )

        middleware = ProxyPrefixMiddleware(get_response)
        response = middleware(request)

        get_response.assert_called_once_with(request)
        self.assertEqual(response, "middleware_response")
        self.assertEqual(request.build_absolute_uri(), "http://testserver/test/path")
