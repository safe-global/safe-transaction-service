from django.test import TestCase

from django_test_migrations.migrator import Migrator


class TestMigrations(TestCase):
    def setUp(self) -> None:
        self.migrator = Migrator(database="default")
