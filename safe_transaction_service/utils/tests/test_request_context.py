# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import SimpleTestCase

from ..request_context import (
    SAFE_REQ_ID_HEADER,
    get_event_headers,
    get_safe_req_id,
    reset_safe_req_id,
    set_safe_req_id,
)

SAFE_REQ_ID = "0123456789abcdef0123456789abcdef"


class TestRequestContext(SimpleTestCase):
    def test_safe_req_id_not_set(self):
        self.assertIsNone(get_safe_req_id())
        self.assertIsNone(get_event_headers())

    def test_set_valid_safe_req_id(self):
        token = set_safe_req_id(SAFE_REQ_ID)
        try:
            self.assertEqual(get_safe_req_id(), SAFE_REQ_ID)
            self.assertEqual(get_event_headers(), {SAFE_REQ_ID_HEADER: SAFE_REQ_ID})
        finally:
            reset_safe_req_id(token)
        self.assertIsNone(get_safe_req_id())

    def test_set_invalid_safe_req_id(self):
        for value in (
            None,
            "",
            SAFE_REQ_ID.upper(),
            SAFE_REQ_ID[:-1],
            SAFE_REQ_ID + "0",
            SAFE_REQ_ID + "\n",
            f"{SAFE_REQ_ID},{SAFE_REQ_ID}",  # Header sent twice
            "0123456789abcdef0123456789abcdeg",
        ):
            with self.subTest(value=value):
                token = set_safe_req_id(value)
                try:
                    self.assertIsNone(get_safe_req_id())
                    self.assertIsNone(get_event_headers())
                finally:
                    reset_safe_req_id(token)

    def test_reset_restores_previous_value(self):
        outer_token = set_safe_req_id(SAFE_REQ_ID)
        try:
            inner_token = set_safe_req_id(None)
            self.assertIsNone(get_safe_req_id())
            reset_safe_req_id(inner_token)
            self.assertEqual(get_safe_req_id(), SAFE_REQ_ID)
        finally:
            reset_safe_req_id(outer_token)
