from django.core.management.base import BaseCommand

from ...tasks import (create_missing_contracts_with_metadata_task,
                      reindex_contracts_without_metadata)


class Command(BaseCommand):
    help = 'Index contracts from etherscan/sourcify'

    def add_arguments(self, parser):
        parser.add_argument('--reindex', help='Try to fetch contract names/ABIS for contracts already indexed',
                            action='store_true', default=False)
        parser.add_argument('--async', help='Trigger an async task', action='store_true', default=False)

    def handle(self, *args, **options):
        reindex = options['reindex']
        not_sync = options['async']

        if reindex:
            task = reindex_contracts_without_metadata
        else:
            task = create_missing_contracts_with_metadata_task

        self.stdout.write(self.style.SUCCESS('Triggering task'))
        if not_sync:
            task.delay()
            self.stdout.write(self.style.SUCCESS('Task was sent'))
        else:
            task()
            self.stdout.write(self.style.SUCCESS('Processing finished'))
