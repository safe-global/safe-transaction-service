# SPDX-License-Identifier: FSL-1.1-MIT
import json
import logging
import sys
from logging import LogRecord

from django.test import TestCase

from ...loggers.custom_logger import IgnoreSucceededNone, SafeJsonFormatter


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
