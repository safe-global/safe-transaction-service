# SPDX-License-Identifier: FSL-1.1-MIT
import logging
import unittest
from unittest.mock import MagicMock

from django.test import RequestFactory, TestCase
from django.urls import reverse

from ...utils.request_context import SAFE_REQ_ID_HEADER, get_safe_req_id
from ...utils.tests.constants import SAFE_REQ_ID
from ..proxy_prefix_middleware import ProxyPrefixMiddleware
from ..safe_request_id_middleware import SafeRequestIdMiddleware


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

    def test_safe_request_id_middleware(self):
        """The header is set while serving the request and cleared after"""
        get_response = MagicMock(side_effect=lambda request: get_safe_req_id())
        middleware = SafeRequestIdMiddleware(get_response)
        for header in (SAFE_REQ_ID_HEADER, "X-Safe-Req-Id"):
            with self.subTest(header=header):
                request = RequestFactory().get(
                    "/test/path", headers={header: SAFE_REQ_ID}
                )
                self.assertEqual(middleware(request), SAFE_REQ_ID)
                self.assertIsNone(get_safe_req_id())


class TestSafeRequestIdMiddlewareOrder(TestCase):
    def test_request_id_is_set_when_logging_middleware_logs(self):
        """
        LoggingMiddleware logs after the response, so SafeRequestIdMiddleware
        must run before it for the "Http request" line to have the id
        """
        seen_safe_req_ids = []

        class RecordSafeReqIdHandler(logging.Handler):
            def emit(self, record):
                seen_safe_req_ids.append(get_safe_req_id())

        logger = logging.getLogger("LoggingMiddleware")
        handler = RecordSafeReqIdHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.INFO)

        response = self.client.get(
            reverse("v1:history:about"), headers={SAFE_REQ_ID_HEADER: SAFE_REQ_ID}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen_safe_req_ids, [SAFE_REQ_ID])
