# SPDX-License-Identifier: FSL-1.1-MIT
import subprocess
import sys
from unittest import mock

from django.test import SimpleTestCase

from config.celery_app import close_db_connections


class TestCeleryApp(SimpleTestCase):
    def test_celery_app_import_does_not_import_django_db(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, sys; os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'; import config.celery_app; raise SystemExit('django.db' in sys.modules)",
            ],
            check=False,
        )

        self.assertEqual(result.returncode, 0)

    def test_db_connections_closed_after_task(self):
        conn_to_close = mock.Mock(in_atomic_block=False)
        conn_in_atomic = mock.Mock(in_atomic_block=True)

        with mock.patch(
            "django.db.connections.all",
            return_value=[conn_to_close, conn_in_atomic],
        ) as mock_all:
            close_db_connections()

        mock_all.assert_called_once_with(initialized_only=True)
        conn_to_close.close_if_unusable_or_obsolete.assert_called_once_with()
        conn_in_atomic.close_if_unusable_or_obsolete.assert_not_called()
