# SPDX-License-Identifier: FSL-1.1-MIT
from logging import LogRecord

from django.test import TestCase

from ...loggers.custom_logger import IgnoreCheckUrl, IgnoreSucceededNone


class TestLoggers(TestCase):
    def test_ignore_check_url(self):
        name = "name"
        level = 1
        pathname = "/"
        lineno = 2
        ignore_check_url = IgnoreCheckUrl(name)

        def build_log(message: str) -> LogRecord:
            return LogRecord(
                name, level, pathname, lineno, message, args=(), exc_info=()
            )

        for message in (
            "200 GET /check/",
            "200 GET /health/live",
            "200 GET /health/live/",
            "200 GET /health/ready",
            "200 GET /health/ready/",
        ):
            with self.subTest(message=message):
                self.assertFalse(ignore_check_url.filter(build_log(message)))

        for message in (
            "200 GET /not-check/",
            "200 GET /api/v1/about/",
            "503 GET /health/ready",
        ):
            with self.subTest(message=message):
                self.assertTrue(ignore_check_url.filter(build_log(message)))

    def test_ignore_succeeded_none(self):
        name = "name"
        level = 1
        pathname = "/"
        lineno = 2
        ignore_check_url = IgnoreSucceededNone(name)
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
        self.assertFalse(ignore_check_url.filter(task_log))
        self.assertTrue(ignore_check_url.filter(other_log))
