# SPDX-License-Identifier: FSL-1.1-MIT
import os
import subprocess
import sys
import threading
import warnings
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from celery.exceptions import CPendingDeprecationWarning
from celery.worker.consumer import Consumer

from config.celery_app import app, close_db_connections


class TestCeleryApp(SimpleTestCase):
    def _run_python(self, code: str, **kwargs) -> str:
        """
        Run ``code`` in a fresh interpreter, so modules imported by the test run do
        not hide import order problems. It inherits the environment by default.

        :return: stdout of the process
        """
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
            **kwargs,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_celery_app_import_does_not_import_django_db(self):
        self._run_python(
            "import sys; import config.celery_app; raise SystemExit('django.db' in sys.modules)"
        )

    def test_shared_tasks_use_project_app_in_new_threads(self):
        """
        Django startup alone must bind ``shared_task`` tasks to the project app, also
        in threads other than the one that imported it (e.g. web request greenlets).
        Covers the ``config.wsgi`` order: ``config`` is imported before
        ``DJANGO_SETTINGS_MODULE`` is set, and after ``current_app`` was read
        """
        code = """
import os
import threading

from celery import current_app

current_app.main

import config  # noqa

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"

import django

django.setup()

from safe_transaction_service.history.tasks import retry_get_metadata_task as task


def check():
    print(task.app.main, task.app.amqp.router.route({}, task.name)["queue"].name)


thread = threading.Thread(target=check)
thread.start()
thread.join()
"""
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "DJANGO_SETTINGS_MODULE"
        }
        stdout = self._run_python(code, env=env)

        self.assertEqual(
            stdout.strip().splitlines()[-1], "safe_transaction_service tokens"
        )

    def test_gunicorn_conf_does_not_import_celery(self):
        # See the comment in gunicorn.conf.py
        self._run_python(
            "import runpy, sys; runpy.run_path('gunicorn.conf.py'); raise SystemExit('celery' in sys.modules)",
            cwd=settings.ROOT_DIR,
        )

    def test_celery_beat_admin_uses_project_app_in_new_threads(self):
        """
        django-celery-beat admin reads Celery's ``current_app`` on every request, so
        the task dropdown and the "Run selected tasks" action must get the project app
        in threads other than the main one (web requests)
        """
        code = """
import threading
from unittest import mock

import django

django.setup()

from celery.app.task import Task
from django.contrib.admin import site
from django_celery_beat.admin import PeriodicTaskAdmin, TaskSelectWidget
from django_celery_beat.models import PeriodicTask

task_name = "safe_transaction_service.history.tasks.reindex_mastercopies_last_hours_task"
model_admin = PeriodicTaskAdmin(PeriodicTask, site)


def check():
    print(task_name in dict(TaskSelectWidget().tasks_as_choices()))
    with (
        mock.patch.object(model_admin, "message_user") as message_user_mock,
        mock.patch.object(Task, "apply_async", autospec=True) as apply_async_mock,
    ):
        model_admin.run_tasks(None, [PeriodicTask(name="test", task=task_name)])
    print(message_user_mock.call_args.args[1])
    task = apply_async_mock.call_args.args[0]
    print(task.app.main, task.app.amqp.router.route({}, task.name)["queue"].name)


thread = threading.Thread(target=check)
thread.start()
thread.join()
"""
        stdout = self._run_python(code)

        self.assertEqual(
            stdout.strip().splitlines()[-3:],
            [
                "True",
                "1 task was successfully run",
                "safe_transaction_service indexing",
            ],
        )

    def test_control_and_event_queues_are_durable_and_not_exclusive(self):
        """
        Control and event queues are durable and not exclusive, and Celery can build
        the control mailbox
        """
        mailbox = app.control.mailbox

        self.assertTrue(mailbox.queue_durable)
        self.assertFalse(mailbox.queue_exclusive)
        self.assertTrue(app.conf.event_queue_durable)
        self.assertFalse(app.conf.event_queue_exclusive)

    def test_prefetch_count_not_reduced_after_broker_connection_loss(self):
        """
        A worker that loses the broker connection while running tasks reconnects with
        its full prefetch count, and finished tasks do not try to restore it
        """
        concurrency = 100
        prefetch_multiplier = 2
        consumer = Consumer(
            mock.Mock(),
            app=app,
            pool=mock.Mock(num_processes=concurrency),
            controller=mock.Mock(),
            initial_prefetch_count=concurrency * prefetch_multiplier,
            prefetch_multiplier=prefetch_multiplier,
        )
        running_requests = {mock.Mock() for _ in range(50)}

        with (
            mock.patch(
                "celery.worker.consumer.consumer.active_requests", running_requests
            ),
            # Unrelated warning about worker_cancel_long_running_tasks_on_connection_loss
            warnings.catch_warnings(
                category=CPendingDeprecationWarning, action="ignore"
            ),
        ):
            # The handler logs the exception being handled
            try:
                raise ConnectionError("Broker connection lost")
            except ConnectionError as exc:
                consumer.on_connection_error_after_connected(exc)

        self.assertFalse(app.conf.worker_enable_prefetch_count_reduction)
        self.assertEqual(
            consumer.initial_prefetch_count, concurrency * prefetch_multiplier
        )

        # Celery calls the restore when a task finishes after the reconnect
        consumer.qos = mock.Mock(
            value=consumer.initial_prefetch_count, _mutex=threading.Lock()
        )
        consumer._restore_prefetch_count_after_connection_restart(None)
        consumer.qos.set.assert_not_called()

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
