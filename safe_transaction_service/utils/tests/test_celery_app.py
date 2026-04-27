# SPDX-License-Identifier: FSL-1.1-MIT
from unittest import mock

from django.db import connection
from django.test import TransactionTestCase

from safe_transaction_service.history.tasks import delete_expired_delegates_task


class TestCeleryApp(TransactionTestCase):
    def test_db_connection_closed_after_task(self):
        # TransactionTestCase is required: TestCase wraps each test in a transaction
        # (in_atomic_block=True), which our signal handler deliberately skips to avoid
        # breaking test isolation. TransactionTestCase has no wrapping transaction, so
        # the handler actually runs and closes the connection.
        with mock.patch.object(
            connection,
            "close_if_unusable_or_obsolete",
            wraps=connection.close_if_unusable_or_obsolete,
        ) as mock_close:
            delete_expired_delegates_task.apply()
            mock_close.assert_called_once()
        self.assertIsNone(connection.connection)
