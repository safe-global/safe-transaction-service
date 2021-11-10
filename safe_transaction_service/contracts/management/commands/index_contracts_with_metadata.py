from django.core.management.base import BaseCommand

from ...tasks import (
    create_missing_contracts_with_metadata_task,
    reindex_contracts_without_metadata_task,
)


class Command(BaseCommand):
    help = "Index contracts from etherscan/sourcify"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reindex",
            help="Try to fetch contract names/ABIS for contracts already indexed. "
            "If not provided only missing contracts will be processed",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--sync",
            help="Command will wait for the command to run. If not provided an async task will be used",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        reindex = options["reindex"]
        sync = options["sync"]

        if reindex:
            self.stdout.write(
                self.style.SUCCESS(
                    "Calling `reindex_contracts_without_metadata_task` task"
                )
            )
            task = reindex_contracts_without_metadata_task
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Calling `create_missing_contracts_with_metadata_task` task"
                )
            )
            task = create_missing_contracts_with_metadata_task

        if sync:
            task()
            self.stdout.write(self.style.SUCCESS("Processing finished"))
        else:
            task.delay()
            self.stdout.write(self.style.SUCCESS("Task was sent"))
