from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class TestCommands(TestCase):
    def test_index_contracts_with_metadata(self):
        command = "index_contracts_with_metadata"

        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn(
            "Calling `create_missing_contracts_with_metadata_task` task", buf.getvalue()
        )
        self.assertIn("Task was sent", buf.getvalue())

        buf = StringIO()
        call_command(command, "--reindex", "--sync", stdout=buf)
        self.assertIn(
            "Calling `reindex_contracts_without_metadata_task` task", buf.getvalue()
        )
        self.assertIn("Processing finished", buf.getvalue())
