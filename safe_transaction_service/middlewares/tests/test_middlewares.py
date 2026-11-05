# SPDX-License-Identifier: FSL-1.1-MIT
import logging
import unittest
from unittest.mock import MagicMock

from django.test import RequestFactory, TestCase
from django.urls import reverse

from ...utils.request_context import get_safe_req_id
from ..proxy_prefix_middleware import ProxyPrefixMiddleware
from ..safe_request_id_middleware import SafeRequestIdMiddleware

SAFE_REQ_ID = "0123456789abcdef0123456789abcdef"


class TestMiddlewares(unittest.TestCase):
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

    def _call_safe_request_id_middleware(self, headers: dict[str, str] | None = None):
        seen = []

        def get_response(request):
            seen.append(get_safe_req_id())
            return "middleware_response"

        request = RequestFactory().get("/test/path", headers=headers)
        response = SafeRequestIdMiddleware(get_response)(request)
        return response, seen[0]

    def test_safe_request_id_middleware(self):
        response, seen = self._call_safe_request_id_middleware(
            {"x-safe-req-id": SAFE_REQ_ID}
        )
        self.assertEqual(response, "middleware_response")
        self.assertEqual(seen, SAFE_REQ_ID)
        self.assertIsNone(get_safe_req_id())

        _, seen = self._call_safe_request_id_middleware({"X-Safe-Req-Id": SAFE_REQ_ID})
        self.assertEqual(seen, SAFE_REQ_ID)

    def test_safe_request_id_middleware_invalid_or_missing_header(self):
        for headers in (None, {"x-safe-req-id": "not-a-request-id"}):
            with self.subTest(headers=headers):
                _, seen = self._call_safe_request_id_middleware(headers)
                self.assertIsNone(seen)
                self.assertIsNone(get_safe_req_id())

    def test_safe_request_id_middleware_does_not_leak_to_next_request(self):
        _, seen = self._call_safe_request_id_middleware({"x-safe-req-id": SAFE_REQ_ID})
        self.assertEqual(seen, SAFE_REQ_ID)
        _, seen = self._call_safe_request_id_middleware()
        self.assertIsNone(seen)

    def test_safe_request_id_middleware_resets_on_exception(self):
        get_response = MagicMock(side_effect=ValueError)
        request = RequestFactory().get(
            "/test/path", headers={"x-safe-req-id": SAFE_REQ_ID}
        )
        with self.assertRaises(ValueError):
            SafeRequestIdMiddleware(get_response)(request)
        self.assertIsNone(get_safe_req_id())


class TestSafeRequestIdMiddlewareOrder(TestCase):
    def test_request_id_is_set_when_logging_middleware_logs(self):
        seen = []

        class RecordSafeReqIdHandler(logging.Handler):
            def emit(self, record):
                seen.append(get_safe_req_id())

        logger = logging.getLogger("LoggingMiddleware")
        handler = RecordSafeReqIdHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.INFO)

        response = self.client.get(
            reverse("v1:history:about"), headers={"x-safe-req-id": SAFE_REQ_ID}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, [SAFE_REQ_ID])
