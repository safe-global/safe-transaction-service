from django.test import TestCase

from celery.app.task import Task as CeleryTask
from redis.exceptions import LockError

from ..tasks import only_one_running_task


class TestTasks(TestCase):
    def test_only_one_running_task(self):
        celery_task = CeleryTask()
        celery_task.name = "Test Name"
        with only_one_running_task(celery_task):
            with self.assertRaises(LockError):
                with only_one_running_task(celery_task):
                    pass
