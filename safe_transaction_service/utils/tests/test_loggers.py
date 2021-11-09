from logging import LogRecord

from django.test import TestCase

from ..loggers import IgnoreCheckUrl


class TestLoggers(TestCase):
    def test_ignore_check_url(self):
        name = "name"
        level = 1
        pathname = "/"
        lineno = 2
        ignore_check_url = IgnoreCheckUrl(name)
        check_log = LogRecord(
            name, level, pathname, lineno, "200 GET /check/", args=(), exc_info=()
        )
        other_log = LogRecord(
            name, level, pathname, lineno, "200 GET /not-check/", args=(), exc_info=()
        )
        self.assertFalse(ignore_check_url.filter(check_log))
        self.assertTrue(ignore_check_url.filter(other_log))
