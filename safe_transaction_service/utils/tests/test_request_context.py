# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import SimpleTestCase

from ..request_context import get_safe_req_id, safe_req_id_context

SAFE_REQ_ID = "0123456789abcdef0123456789abcdef"
LOGGER_NAME = "safe_transaction_service.utils.request_context"


class TestRequestContext(SimpleTestCase):
    def test_valid_safe_req_id(self):
        with self.assertNoLogs(LOGGER_NAME), safe_req_id_context(SAFE_REQ_ID):
            self.assertEqual(get_safe_req_id(), SAFE_REQ_ID)
        self.assertIsNone(get_safe_req_id())

    def test_missing_safe_req_id(self):
        with self.assertNoLogs(LOGGER_NAME), safe_req_id_context(None):
            self.assertIsNone(get_safe_req_id())

    def test_invalid_safe_req_id(self):
        for value in (
            "",
            SAFE_REQ_ID.upper(),
            SAFE_REQ_ID[:-1],
            SAFE_REQ_ID + "0",
            SAFE_REQ_ID + "\n",
            f"{SAFE_REQ_ID},{SAFE_REQ_ID}",  # Header sent twice
            "0123456789abcdef0123456789abcdeg",
            "a" * 1000,
        ):
            with self.subTest(value=value):
                with (
                    self.assertLogs(LOGGER_NAME, level="WARNING") as cm,
                    safe_req_id_context(value),
                ):
                    self.assertIsNone(get_safe_req_id())
                self.assertEqual(
                    cm.records[0].getMessage(),
                    f"Ignoring invalid x-safe-req-id header: {value[:64]!r}",
                )

    def test_exit_restores_previous_value(self):
        with safe_req_id_context(SAFE_REQ_ID):
            with safe_req_id_context(None):
                self.assertIsNone(get_safe_req_id())
            self.assertEqual(get_safe_req_id(), SAFE_REQ_ID)
        self.assertIsNone(get_safe_req_id())

    def test_exit_restores_previous_value_on_exception(self):
        with self.assertRaises(ValueError), safe_req_id_context(SAFE_REQ_ID):
            raise ValueError
        self.assertIsNone(get_safe_req_id())
