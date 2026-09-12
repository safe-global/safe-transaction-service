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

        def build_log(
            status: str,
            path: str,
            method: str = "GET",
            remote_address: str = "127.0.0.1",
        ) -> LogRecord:
            """
            Build a record the way Gunicorn does, passing the access log atoms
            as the record arguments.
            """
            atoms = {
                "h": remote_address,
                "m": method,
                "U": path,
                "q": "",
                "s": status,
                "a": "python-requests/2.32.3",
            }
            return LogRecord(
                name,
                level,
                pathname,
                lineno,
                "%(h)s %(m)s %(U)s %(s)s %(a)s",
                args=(atoms,),
                exc_info=(),
            )

        for status, path in (
            ("200", "/check/"),
            ("200", "/health/live"),
            ("200", "/health/live/"),
            ("200", "/health/ready"),
            ("200", "/health/ready/"),
        ):
            with self.subTest(status=status, path=path):
                self.assertFalse(ignore_check_url.filter(build_log(status, path)))

        for status, path in (
            ("200", "/not-check/"),
            ("200", "/api/v1/about/"),
            ("503", "/health/ready"),
            ("503", "/check/"),
        ):
            with self.subTest(status=status, path=path):
                self.assertTrue(ignore_check_url.filter(build_log(status, path)))

        with self.subTest("Only GET is a probe"):
            self.assertTrue(
                ignore_check_url.filter(build_log("200", "/check/", method="POST"))
            )

        with self.subTest("A 200 elsewhere in the line does not drop a failing probe"):
            self.assertTrue(
                ignore_check_url.filter(
                    build_log("503", "/health/ready", remote_address="2001:db8::1")
                )
            )

        with self.subTest("Records without atoms are kept"):
            self.assertTrue(
                ignore_check_url.filter(
                    LogRecord(
                        name,
                        level,
                        pathname,
                        lineno,
                        "200 GET /check/",
                        args=(),
                        exc_info=(),
                    )
                )
            )

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
