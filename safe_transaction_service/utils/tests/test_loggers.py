# SPDX-License-Identifier: FSL-1.1-MIT
import json
import logging
import sys
from logging import LogRecord

from django.test import TestCase

from ...loggers.custom_logger import IgnoreSucceededNone, SafeJsonFormatter
from ..request_context import safe_req_id_context
from .constants import SAFE_REQ_ID


class TestLoggers(TestCase):
    def test_ignore_succeeded_none(self):
        name = "name"
        level = 1
        pathname = "/"
        lineno = 2
        ignore_succeeded_none = IgnoreSucceededNone(name)
        task_log = LogRecord(
            name,
            level,
            pathname,
            lineno,
            "Task safe_transaction_service.history.tasks.index_internal_"
            "txs_task[89ad3c46-aeb3-48a1-bd6f-2f3684323ca8] succeeded in "
            "1.0970600529108196s: None",
            args=(),
            exc_info=(),
        )
        other_log = LogRecord(
            name, level, pathname, lineno, "Not a task log", args=(), exc_info=()
        )
        self.assertFalse(ignore_succeeded_none.filter(task_log))
        self.assertTrue(ignore_succeeded_none.filter(other_log))

    def test_safe_json_formatter_exception_info(self):
        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()

        for level in (logging.WARNING, logging.ERROR, logging.CRITICAL):
            with self.subTest(level=level):
                record = LogRecord(
                    "name", level, "/", 2, "Test message", args=(), exc_info=exc_info
                )
                error_info = json.loads(SafeJsonFormatter().format(record))[
                    "contextMessage"
                ]["errorInfo"]
                self.assertIn("ValueError: Test exception", error_info["exceptionInfo"])

        record = LogRecord(
            "name", logging.WARNING, "/", 2, "Test message", args=(), exc_info=None
        )
        self.assertNotIn(
            "errorInfo",
            json.loads(SafeJsonFormatter().format(record))["contextMessage"],
        )

    def test_safe_json_formatter_timestamp(self):
        record = LogRecord(
            "name", logging.INFO, "/", 2, "Test message", args=(), exc_info=None
        )
        record.created = 1700000000.123
        self.assertEqual(
            json.loads(SafeJsonFormatter().format(record))["timestamp"], 1700000000123
        )

    def test_safe_json_formatter_request_id(self):
        """JSON logs include requestId only while a request id is set"""
        record = LogRecord(
            "name", logging.INFO, "/", 2, "Test message", args=(), exc_info=None
        )
        self.assertNotIn(
            "requestId",
            json.loads(SafeJsonFormatter().format(record))["contextMessage"],
        )

        with safe_req_id_context(SAFE_REQ_ID):
            context_message = json.loads(SafeJsonFormatter().format(record))[
                "contextMessage"
            ]
        self.assertEqual(context_message["requestId"], SAFE_REQ_ID)

    def test_safe_json_formatter_datadog_trace_fields(self):
        """The dd.* attributes ddtrace adds to a record end up in a "dd" object."""
        record = logging.makeLogRecord(
            {
                "levelno": logging.INFO,
                "dd.trace_id": "6afad78300000000a4289ab1112176c0",
                "dd.span_id": "14239931113675422624",
                "dd.service": "mainnet-safe-transaction-web",
                "dd.version": "v6.14.0",
                "dd.env": "production",
            }
        )

        log = json.loads(SafeJsonFormatter().format(record))

        self.assertEqual(
            log["dd"],
            {
                "trace_id": "6afad78300000000a4289ab1112176c0",
                "span_id": "14239931113675422624",
                "service": "mainnet-safe-transaction-web",
                "version": "v6.14.0",
                "env": "production",
            },
        )

    def test_safe_json_formatter_without_datadog_tracer(self):
        """Without ddtrace the record has no dd.* attributes and the log no "dd" key."""
        record = LogRecord(
            "name", logging.INFO, "/", 2, "Test message", args=(), exc_info=None
        )

        self.assertNotIn("dd", json.loads(SafeJsonFormatter().format(record)))

    def test_safe_json_formatter_datadog_trace_fields_outside_span(self):
        """Outside a span ddtrace sets trace_id "0", so only service, version and env are written."""
        record = logging.makeLogRecord(
            {
                "levelno": logging.INFO,
                "dd.trace_id": "0",
                "dd.span_id": "0",
                "dd.service": "mainnet-safe-transaction-web",
                "dd.version": "v6.14.0",
                "dd.env": "production",
            }
        )

        log = json.loads(SafeJsonFormatter().format(record))

        self.assertEqual(
            log["dd"],
            {
                "service": "mainnet-safe-transaction-web",
                "version": "v6.14.0",
                "env": "production",
            },
        )

    def test_safe_json_formatter_omits_empty_datadog_trace_fields(self):
        """Version and env are empty without DD_VERSION and DD_ENV, so they are not written."""
        record = logging.makeLogRecord(
            {
                "dd.trace_id": "6afad78300000000a4289ab1112176c0",
                "dd.span_id": "14239931113675422624",
                "dd.service": "mainnet-safe-transaction-web",
                "dd.version": "",
                "dd.env": "",
                "levelno": logging.INFO,
            }
        )

        log = json.loads(SafeJsonFormatter().format(record))

        self.assertEqual(
            log["dd"],
            {
                "trace_id": "6afad78300000000a4289ab1112176c0",
                "span_id": "14239931113675422624",
                "service": "mainnet-safe-transaction-web",
            },
        )

    def test_safe_json_formatter_writes_only_present_datadog_trace_fields(self):
        """A record with dd.trace_id but no other dd.* attribute writes only the trace id."""
        record = logging.makeLogRecord(
            {"dd.trace_id": "6afad78300000000a4289ab1112176c0", "levelno": logging.INFO}
        )

        log = json.loads(SafeJsonFormatter().format(record))

        self.assertEqual(log["dd"], {"trace_id": "6afad78300000000a4289ab1112176c0"})

    def test_safe_json_formatter_omits_dd_key_when_all_datadog_fields_are_empty(self):
        """Outside a span with empty service, version and env there is nothing to write."""
        record = logging.makeLogRecord(
            {
                "dd.trace_id": "0",
                "dd.span_id": "0",
                "dd.service": "",
                "dd.version": "",
                "dd.env": "",
                "levelno": logging.INFO,
            }
        )

        log = json.loads(SafeJsonFormatter().format(record))

        self.assertNotIn("dd", log)
